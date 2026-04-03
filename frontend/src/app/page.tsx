import LandingNav from "@/components/landing/LandingNav";
import HeroSection from "@/components/landing/HeroSection";
import PainPointSection from "@/components/landing/PainPointSection";
import DemoTeaserSection from "@/components/landing/DemoTeaserSection";
import HowItWorksSection from "@/components/landing/HowItWorksSection";
import FinalCtaSection from "@/components/landing/FinalCtaSection";
import ThemeSwitcher from "@/components/landing/ThemeSwitcher";

export const dynamic = "force-static";

export default function LandingPage() {
  return (
    <>
      <LandingNav />
      <main>
        <HeroSection />
        <PainPointSection />
        <DemoTeaserSection />
        <section id="how-it-works">
          <HowItWorksSection />
        </section>
        <section id="pricing">
          <FinalCtaSection />
        </section>
      </main>
      <ThemeSwitcher />
    </>
  );
}
