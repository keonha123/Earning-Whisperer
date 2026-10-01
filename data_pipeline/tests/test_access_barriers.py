"""Real DOM barrier regressions; every network request is aborted or fulfilled."""
import json
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser import session
from data_pipeline.collectors.streams.browser.access_barriers import flow_surfaces
from data_pipeline.collectors.streams.browser.form_validation import collect_registration_validation, registration_transition_state


class Target:
    def __init__(self, page, url='https://fixture.test/event/player'):
        self.page, self.url = page, url
    def __getattr__(self, key):
        return getattr(self.page, key)


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class AccessBarrierBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        opts = {'headless': True, 'args': ['--no-sandbox', '--disable-background-networking', '--disable-dev-shm-usage']}
        if os.getenv('WEBCAST_CHROMIUM_EXECUTABLE'):
            opts['executable_path'] = os.environ['WEBCAST_CHROMIUM_EXECUTABLE']
        self.browser = await self.pw.chromium.launch(**opts)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route('**/*', lambda route: route.abort())
        self.agent = SimpleNamespace(ticker='FIXTURE', _page_http_status=200)

    async def barriers(self, html):
        await self.page.set_content(html)
        return (await session._detect_access_barrier(self.agent, self.page),
                await session._detect_registration_barrier(self.agent, self.page))

    async def test_original_cost_hidden_captcha_frame_does_not_block_q4_link(self):
        result = await self.barriers('''<h1>Q4 2026 Earnings Call</h1><a href="/webcast">Webcast</a>
            <iframe style="display:none" srcdoc="<body>reCAPTCHA</body>"></iframe>''')
        self.assertEqual(result, (None, None))
        self.assertEqual(self.agent._access_barrier_evidence['surfaces'][1]['reason'], 'hidden_embedding')

    async def test_hidden_ancestor_hides_nested_frame_despite_own_visible_body(self):
        await self.page.set_content('''<h1>Q4 Earnings Call</h1><div hidden><iframe title="Webcast"></iframe></div>''')
        frame = self.page.frames[1]
        await frame.set_content('<iframe title="Webcast"></iframe>')
        await frame.child_frames[0].set_content('<body>Verify you are human</body>')
        self.assertIsNone(await session._detect_access_barrier(self.agent, self.page))
        self.assertFalse((await flow_surfaces(self.page))[-1]['visible'])

    async def test_hidden_main_challenge_and_hidden_login_are_not_barriers(self):
        self.assertEqual(await self.barriers('''<h1>Q4 Earnings Call</h1>
            <div style="visibility:hidden">Verify you are human</div>
            <form hidden>Please log in to access the webcast E-mail Login</form>'''), (None, None))

    async def test_opacity_zero_frame_is_not_a_visible_gate(self):
        self.assertEqual(await self.barriers('''<h1>Q4 Earnings Call</h1>
            <iframe title="Webcast" style="opacity:0" srcdoc="<body>captcha</body>"></iframe>'''), (None, None))

    async def test_visible_unrelated_ad_frame_is_not_global_barrier(self):
        self.assertEqual(await self.barriers('''<h1>Q4 Earnings Call</h1><a href="/webcast">Webcast</a>
            <iframe title="Advertisement" srcdoc="<body>Access denied. Verify you are human.</body>"></iframe>'''), (None, None))
        self.assertEqual(self.agent._access_barrier_evidence['surfaces'][1]['reason'], 'unrelated_embedding')

    async def test_passive_captcha_badge_and_attribution_are_not_gate(self):
        self.assertEqual(await self.barriers('''<h1>Q4 Earnings Call</h1><a href="/webcast">Webcast</a>
            <div class="grecaptcha-badge">This site is protected by reCAPTCHA</div>
            <footer><iframe title="reCAPTCHA" srcdoc="<body>reCAPTCHA</body>"></iframe></footer>'''), (None, None))

    async def test_visible_main_human_challenge_is_blocked_without_interaction(self):
        result = await self.barriers('''<h1>Verify you are human</h1><button onclick="window.clicked=true">Continue</button>''')
        self.assertIn('manual verification', result[0])
        self.assertIn('manual verification', result[1])
        self.assertIsNone(await self.page.evaluate('window.clicked'))

    async def test_actual_visible_captcha_wrapper_in_form_is_blocked_even_without_text(self):
        result = await self.barriers('''<form><h1>Webcast Registration</h1><input type="email">
            <div class="g-recaptcha" data-sitekey="fixture"><iframe title="reCAPTCHA"></iframe></div>
            <button>Register</button></form>''')
        self.assertIn('manual verification', result[0])
        self.assertIn('manual verification', result[1])

    async def test_visible_challenge_inside_player_frame_is_blocked(self):
        result = await self.barriers('''<h1>Q4 Earnings Call</h1>
            <iframe title="Webcast player" srcdoc="<body>Performing security verification before continuing</body>"></iframe>''')
        self.assertEqual(result[0], 'Performing security verification')

    async def test_visible_captcha_inside_registration_frame_is_blocked(self):
        result = await self.barriers('''<h1>Q4 Earnings Call</h1><iframe title="Webcast Registration"
            srcdoc="<form><label>I’m not a robot</label><input type='checkbox'></form>"></iframe>''')
        self.assertIn('manual verification', result[0])
        self.assertIn('manual verification', result[1])

    async def test_full_page_iframe_security_gate_is_blocked(self):
        result = await self.barriers('<iframe srcdoc="<body>Performing security verification before continuing</body>"></iframe>')
        self.assertEqual(result[0], 'Performing security verification')

    async def test_actual_cross_origin_player_challenge_is_blocked(self):
        await self.page.unroute('**/*')
        await self.page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body='<h1>Verify you are human</h1>'))
        await self.page.set_content('<h1>Q4 Earnings Call</h1><iframe title="Webcast" src="https://other.fixture.test/challenge"></iframe>')
        await self.page.frames[1].wait_for_load_state()
        self.assertIn('manual verification', await session._detect_access_barrier(self.agent, self.page))

    async def test_main_http_403_and_top_level_login_still_block(self):
        self.agent._page_http_status = 403
        self.assertEqual(await session._detect_access_barrier(self.agent, self.page), 'HTTP 403')
        self.agent._page_http_status = 200
        self.assertEqual(await session._detect_access_barrier(self.agent, Target(self.page, 'https://fixture.test/login/event')),
                         'AUTH_REQUIRED authentication/login surface')

    async def test_visible_login_form_still_blocks(self):
        result = await self.barriers('''<form><h1>Please log in to access the webcast</h1>
            <label>E-mail</label><input type="email"><button>Login</button></form>''')
        self.assertEqual(result[0], 'AUTH_REQUIRED authentication/login form')

    async def test_unrelated_newsletter_login_does_not_block_current_event(self):
        self.assertEqual(await self.barriers('''<h1>Q4 Earnings Call</h1><a href="/webcast">Webcast</a>
            <aside><form id="newsletter">Please log in E-mail Login<input type="email"></form></aside>'''), (None, None))

    async def test_visible_required_consent_is_retained(self):
        result = await self.barriers('<form><label>Privacy policy: this field is required</label><input type="checkbox" required></form>')
        self.assertEqual(result[1], 'mandatory terms/privacy consent is required')

    async def test_hidden_frame_validation_is_not_reported_as_global_failure(self):
        await self.page.set_content('<iframe title="Registration" hidden srcdoc="<input aria-invalid=\'true\'><div role=\'alert\'>Required</div>"></iframe>')
        result = await collect_registration_validation(self.page.frames[1])
        self.assertTrue(result['available'])
        self.assertEqual(result['invalid_field_count'], 0)
        self.assertEqual(result['error_codes'], [])
        self.assertEqual(result['ignored_surface'], 'hidden_embedding')

    async def test_hidden_or_ad_frame_validation_does_not_fail_player_transition(self):
        for embedding in ['hidden title="Registration"', 'title="Advertisement"']:
            with self.subTest(embedding=embedding):
                await self.page.set_content(f'''<h1>Current player</h1><iframe {embedding}
                    srcdoc="<div role='alert'>Invalid email address</div>"></iframe>''')
                target=Target(self.page)
                agent=SimpleNamespace(has_registration_form=mock.AsyncMock(return_value=False),
                    detect_active_playback=mock.AsyncMock(return_value=True),
                    _detect_access_barrier=mock.AsyncMock(return_value=None),
                    _detect_registration_barrier=mock.AsyncMock(return_value=None))
                result=await registration_transition_state(agent,target,target,target.url)
                self.assertEqual(result, {'state':'passed','reason':'active_playback'})

    async def test_hidden_waiting_room_is_not_positive_registration_transition(self):
        await self.page.set_content('''<h1>Current player</h1><iframe hidden title="Webcast"
            srcdoc="<body>The webcast will begin shortly</body>"></iframe>''')
        target=Target(self.page)
        agent=SimpleNamespace(has_registration_form=mock.AsyncMock(return_value=False),
            detect_active_playback=mock.AsyncMock(return_value=False))
        result=await registration_transition_state(agent,target,target,target.url)
        self.assertEqual(result, {'state':'pending','reason':'no_positive_transition'})

    async def test_diagnostics_have_no_body_values_or_signed_url(self):
        await self.page.set_content('<h1>Verify you are human</h1><input value="Secret Attendee">')
        with mock.patch('data_pipeline.collectors.streams.browser.access_barriers.emit_live_event') as emit:
            target=Target(self.page, 'https://fixture.test/event/private?token=SecretToken')
            await session._detect_access_barrier(self.agent,target)
        serialized=json.dumps(emit.call_args.kwargs)
        self.assertNotIn('Secret',serialized)
        self.assertNotIn('private',serialized)
        self.assertNotIn('token',serialized)
        self.assertIn('visible_human_challenge',serialized)

    async def test_locator_in_hidden_frame_does_not_report_form_errors(self):
        await self.page.set_content('<iframe hidden title="Registration"></iframe>')
        frame=self.page.frames[1]
        await frame.set_content('<form><input type="email" aria-invalid="true"></form>')
        result=await collect_registration_validation(frame.locator('form'))
        self.assertEqual(result['ignored_surface'], 'hidden_embedding')
        self.assertEqual(result['invalid_field_count'], 0)

    async def test_unavailable_dom_is_logged_as_incomplete_not_authentication(self):
        target=SimpleNamespace(url='https://fixture.test/event',frames=[],
            evaluate=mock.AsyncMock(side_effect=RuntimeError('detached')))
        self.assertIsNone(await session._detect_access_barrier(self.agent,target))
        self.assertFalse(self.agent._access_barrier_evidence['inspection_complete'])
