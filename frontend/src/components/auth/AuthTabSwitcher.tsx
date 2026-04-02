"use client";

type Tab = "login" | "signup";

interface AuthTabSwitcherProps {
  activeTab: Tab;
  onChange: (tab: Tab) => void;
  disabled?: boolean;
}

const TABS: { key: Tab; label: string }[] = [
  { key: "login", label: "로그인" },
  { key: "signup", label: "회원가입" },
];

export default function AuthTabSwitcher({ activeTab, onChange, disabled }: AuthTabSwitcherProps) {
  return (
    <div role="tablist" className="bg-gray-800 rounded-lg p-1 flex gap-1">
      {TABS.map(({ key, label }) => (
        <button
          key={key}
          role="tab"
          type="button"
          aria-selected={activeTab === key}
          aria-controls={`${key}-panel`}
          onClick={() => !disabled && onChange(key)}
          className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors duration-150 ${
            disabled ? "pointer-events-none" : ""
          } ${
            activeTab === key
              ? "bg-gray-700 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
