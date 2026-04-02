import HeroSection from "@/components/landing/HeroSection";
import PainPointSection from "@/components/landing/PainPointSection";
import HowItWorksSection from "@/components/landing/HowItWorksSection";
import FinalCtaSection from "@/components/landing/FinalCtaSection";

export const dynamic = "force-static";

export default function LandingPage() {
  return (
    <main>
      <HeroSection />
      <PainPointSection />
      <HowItWorksSection />
      <FinalCtaSection />
    </main>
  );
}
