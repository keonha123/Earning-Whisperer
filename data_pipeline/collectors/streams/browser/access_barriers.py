"""Read-only evidence for visible barriers in the current webcast flow.

An iframe's body is readable even when its embedding element is hidden. Walk
all embedding ancestors before treating that document as a page-level gate.
This module never interacts with, solves, or submits a security challenge.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from data_pipeline.live_telemetry import emit_live_event

_VISIBILITY_JS = r"""element => {
    const visible = e => {
        if (!e || !e.isConnected) return false;
        for (let a=e;a;a=a.parentElement) {
            const s=getComputedStyle(a);
            if (a.matches('[hidden],[inert],[aria-hidden="true"]') || s.display==='none'
                || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0) return false;
        }
        const r=e.getBoundingClientRect(); return r.width>0 && r.height>0;
    };
    if (!visible(element)) return {visible:false,relevant:false,reason:'hidden_embedding'};
    const identity = [element.id,element.className,element.title,element.getAttribute('src'),
        element.getAttribute('aria-label')].filter(x=>typeof x==='string').join(' ');
    const overlay = element.closest('[role="dialog"],[aria-modal="true"],dialog');
    const form = element.closest('form,[role="form"]');
    const label = e => [e.id,e.className,e.getAttribute('aria-label'),
        ...(e.querySelectorAll ? Array.from(e.querySelectorAll('h1,h2,h3,legend')).map(n=>n.innerText) : [])]
        .filter(x=>typeof x==='string').join(' ');
    const unrelated = /newsletter|email.?alerts?|subscribe|advertis|(?:^|[ _-])ads?(?:$|[ _-])/i;
    if (!overlay && (unrelated.test(identity) || (form && unrelated.test(label(form)))))
        return {visible:true,relevant:false,reason:'unrelated_embedding'};
    const r=element.getBoundingClientRect(),s=getComputedStyle(element);
    const covering = ['fixed','absolute'].includes(s.position) && r.width*r.height >= innerWidth*innerHeight*0.5;
    const playerScope=element.closest('[id*="webcast" i],[class*="webcast" i],[id*="player" i],[class*="player" i],[id*="registration" i],[class*="registration" i]');
    // Empty player shells commonly contain only a single, full-document iframe.
    const outsideText=String(document.body?.innerText || '').trim();
    const onlyContent=outsideText.length===0 && document.querySelectorAll('iframe,frame').length===1;
    const provider=/webcast|webinar|player|register|registration|earnings|conference|event|media-server|veracast|on24|metameetings/i.test(identity);
    const peripheral=element.closest('aside,footer,nav,header,[role="complementary"],[role="navigation"]');
    const relevant=!!(overlay || covering || form || playerScope || onlyContent || (!peripheral && provider));
    return {visible:true,relevant,reason:relevant?'visible_flow_embedding':'unrelated_embedding'};
}"""

_SURFACE_JS = r"""() => {
    const visible = e => {
        if (!e || !e.isConnected) return false;
        for(let a=e;a;a=a.parentElement){const s=getComputedStyle(a);
            if(a.matches('[hidden],[inert],[aria-hidden="true"]') || s.display==='none'
                || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0)return false;}
        const r=e.getBoundingClientRect();return r.width>0 && r.height>0;
    };
    const unrelatedForm=f => /newsletter|email.?alerts?|subscribe|search/i.test(
        [f.id,f.className,f.getAttribute('aria-label'),...Array.from(f.querySelectorAll('h1,h2,h3,legend')).map(e=>e.innerText)]
        .filter(x=>typeof x==='string').join(' '));
    const relevant=e => {
        if(e.closest('[role="dialog"],[aria-modal="true"],dialog')) return true;
        const form=e.closest('form,[role="form"]');
        if(form) return !unrelatedForm(form);
        return !e.closest('aside,footer,nav,header,[role="complementary"],[role="navigation"]');
    };
    const fragments=[];const walker=document.createTreeWalker(document.body || document.documentElement,NodeFilter.SHOW_TEXT);
    let n,total=0,visited=0;while((n=walker.nextNode()) && total<12000 && visited++<5000){
        const p=n.parentElement;if(p && !p.closest('script,style,noscript') && visible(p) && relevant(p)){
            const text=n.textContent.replace(/\s+/g,' ').trim();if(text){fragments.push(text);total+=text.length+1;}
        }
    }
    const body=fragments.join(' ').slice(0,12000);
    const challengeSelector='[data-sitekey],.g-recaptcha,.h-captcha,[id*="captcha" i],[class*="captcha" i],iframe[src*="captcha" i],iframe[title*="captcha" i],iframe[src*="challenges.cloudflare.com" i]';
    const controls=Array.from(document.querySelectorAll(challengeSelector)).filter(visible).filter(relevant);
    const captchaControl=controls.some(e=>{
        if(e.closest('form,[role="form"],[role="dialog"],[aria-modal="true"],dialog'))return true;
        // Passive badges/attribution outside a submission flow are not a gate.
        if(/badge/i.test(String(e.className)+' '+e.id))return false;
        return /verify (?:that )?you are human|i['’]?m not a robot|security verification|complete (?:the )?(?:re)?captcha/i.test(body)
            || /^(?:hcaptcha|recaptcha|captcha)(?:\W|$)/i.test(body);
    });
    const challengeText=/verify (?:that )?you are human|i['’]?m not a robot|complete (?:the )?(?:re)?captcha|solve (?:the )?(?:re)?captcha|captcha (?:verification )?(?:is )?required/i.test(body)
        || /^(?:hcaptcha|recaptcha|captcha)(?:\W|$)/i.test(body);
    return {body_text:body,captcha_gate:captchaControl||challengeText,visible_challenge_control:captchaControl,
        text_available:true};
}"""


async def frame_flow_context(surface: Any) -> dict[str, Any]:
    """Return visibility/relevance for a Frame, including every embedding level."""
    parent = getattr(surface, 'parent_frame', None)
    if parent is None:
        return {'visible': True, 'relevant': True, 'reason': 'main_document'}
    current = surface
    unrelated = None
    try:
        for _ in range(12):
            if getattr(current, 'parent_frame', None) is None:
                return unrelated or {'visible': True, 'relevant': True, 'reason': 'visible_flow_embedding'}
            element = await asyncio.wait_for(current.frame_element(), .4)
            try:
                context = await asyncio.wait_for(element.evaluate(_VISIBILITY_JS), .4)
            finally:
                await asyncio.wait_for(element.dispose(), .2)
            if not isinstance(context, dict):
                raise TypeError('unavailable frame context')
            if not context.get('visible'):
                return context
            if not context.get('relevant'):
                unrelated = context
            current = current.parent_frame
        return {'visible': False, 'relevant': False, 'reason': 'embedding_depth_limit'}
    except Exception:
        return {'visible': False, 'relevant': False, 'reason': 'embedding_unavailable'}


async def flow_surfaces(page: Any) -> list[dict[str, Any]]:
    """Main document plus bounded, distinct child-frame contexts."""
    result = [{'surface': page, 'kind': 'main', 'visible': True, 'relevant': True,
               'reason': 'main_document'}]
    frames = getattr(page, 'frames', ())
    if not isinstance(frames, (list, tuple)):
        return result
    main = getattr(page, 'main_frame', None)
    children = [frame for frame in frames[:20] if frame is not page and frame is not main]
    async def bounded_context(frame):
        try:
            return await asyncio.wait_for(frame_flow_context(frame), 1.2)
        except Exception:
            return {'visible': False, 'relevant': False, 'reason': 'embedding_unavailable'}
    contexts = await asyncio.gather(*(bounded_context(frame) for frame in children))
    for frame, context in zip(children, contexts):
        # A Page wrapper can expose its real page's main Frame.
        if context['reason'] != 'main_document':
            result.append({'surface': frame, 'kind': 'frame', **context})
    if len(frames) > 20:
        result.append({'kind': 'frame', 'visible': False, 'relevant': False, 'reason': 'surface_limit'})
    return result


async def surface_barrier_evidence(surface: Any) -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(surface.evaluate(_SURFACE_JS), .8)
        if isinstance(result, dict) and isinstance(result.get('body_text'), str):
            return result
    except Exception:
        pass
    # An unavailable DOM is not affirmative evidence of an authentication gate.
    return {'body_text': '', 'captcha_gate': False, 'text_available': False}


async def inspect_flow_surfaces(surfaces: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    async def inspect(item):
        if not (item['visible'] and item['relevant']):
            return None
        return await surface_barrier_evidence(item['surface'])
    return await asyncio.gather(*(inspect(item) for item in surfaces))


def record_barrier_evidence(agent: Any, mode: str, records: list[dict[str, Any]], barrier: str | None) -> None:
    """Persist only categorical evidence: no body text, values, query or URL path."""
    safe=[]
    for record in records[:21]:
        surface=record.get('surface')
        try:
            host=urlparse(str(getattr(surface, 'url', ''))).hostname or ''
        except Exception:
            host=''
        safe.append({key:value for key,value in {**record,'host':host}.items()
                     if key in {'kind','visible','relevant','reason','host','rule','text_available','visible_challenge_control'}})
    incomplete = any(item.get('text_available') is False or item.get('reason') in
                     {'embedding_unavailable', 'embedding_depth_limit', 'surface_limit'} for item in safe)
    evidence={'mode':mode,'blocked':bool(barrier),'inspection_complete':not incomplete,'surfaces':safe}
    key=f'_{mode}_barrier_evidence'
    if getattr(agent,key,None)==evidence:
        return
    setattr(agent,key,evidence)
    emit_live_event('browser','barrier_evaluated',ticker=getattr(agent,'ticker',None),
                    status='blocked' if barrier else ('unavailable' if incomplete else 'observed'),
                    barrier_evidence=evidence)
