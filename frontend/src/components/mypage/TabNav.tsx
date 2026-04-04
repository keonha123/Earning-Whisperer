"use client";

export type MypageTab = "trades" | "subscription" | "settings";

const TABS: { id: MypageTab; label: string }[] = [
  { id: "trades", label: "거래내역" },
  { id: "subscription", label: "구독관리" },
  { id: "settings", label: "설정" },
];

interface TabNavProps {
  active: MypageTab;
  onChange: (tab: MypageTab) => void;
}

export default function TabNav({ active, onChange }: TabNavProps) {
  return (
    <div className="flex border-b border-gray-800">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`px-5 py-3 text-sm font-medium transition-colors ${
            active === tab.id
              ? "border-b-2 border-accent-500 text-white"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
