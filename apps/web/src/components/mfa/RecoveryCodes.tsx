"use client";

import { useState } from "react";
import { Button, Checkbox, StatusMessage, notify } from "@a11y/ui";

/** Shown ONCE after enrolment. The person must confirm they saved them before continuing. */
export function RecoveryCodes({ codes, onContinue }: { codes: string[]; onContinue: () => void }) {
  const [saved, setSaved] = useState(false);
  const text = codes.join("\n");
  return (
    <div className="flex max-w-xl flex-col gap-4">
      <StatusMessage kind="success">Two-step verification is on.</StatusMessage>
      <p>
        These <strong>{codes.length} recovery codes</strong> let you sign in if you lose your authenticator. Each works <strong>once</strong>. They are shown only now.
        Store them somewhere safe, such as a password manager.
      </p>
      <ul aria-label="Recovery codes" className="grid list-none grid-cols-2 gap-2 p-0">
        {codes.map((c) => <li key={c}><code className="text-lg">{c}</code></li>)}
      </ul>
      <div className="flex flex-wrap gap-3">
        <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(text); notify({ title: "Recovery codes copied", kind: "success" }); }}>Copy all codes</Button>
        <Button variant="secondary" onPress={() => {
          const url = URL.createObjectURL(new Blob([`a11y recovery codes\n\n${text}\n`], { type: "text/plain" }));
          const a = document.createElement("a"); a.href = url; a.download = "a11y-recovery-codes.txt"; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
        }}>Download as a text file</Button>
      </div>
      <Checkbox label="I have saved these recovery codes" isSelected={saved} onChange={setSaved} />
      <div><Button isDisabled={!saved} onPress={onContinue}>Continue</Button></div>
    </div>
  );
}
