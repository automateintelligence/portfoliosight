import { Check, Copy, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChallengeError, postShare } from "../api/http";
import { plain } from "../copy";

type Props = { open: boolean; url: string; privatePreview: boolean; onClose: () => void; /** The human check expired: the page reloads to run it. */ onChallenge?: () => void };

export const MAX_SHARE_URL = 2048;
const ADDRESS = /^[^\s@,<>()"]+@[^\s@,<>()"]+\.[^\s@,<>()"]+$/;

/** Copy the address of this view, or send it by email (fixed message; spec 9.3). */
export function ShareDialog({ open, url, privatePreview, onClose, onChallenge }: Props) {
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    first.current?.focus();
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);

  if (!open) return null;
  const tooLong = url.length > MAX_SHARE_URL;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setStatus("Copying is blocked here; select the link and copy it.");
    }
  };

  const send = async () => {
    const address = to.trim();
    if (!ADDRESS.test(address) || address.length > 254) {
      setStatus(plain.shareBadAddress);
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      const result = await postShare(address, url);
      setStatus(
        result === "sent"
          ? plain.shareSent
          : result === "invalid_recipient"
            ? plain.shareBadAddress
            : result === "rate_limited"
              ? plain.shareTooMany
              : result === "invalid_url"
                ? plain.shareTooLong
                : plain.shareFailed,
      );
    } catch (err) {
      if (err instanceof ChallengeError && onChallenge) onChallenge();
      else setStatus(plain.shareFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="share-title">
        <div className="dialog-head">
          <h2 id="share-title" className="heading">
            Share this view
          </h2>
          <button type="button" className="btn btn-icon btn-quiet" aria-label="Close" onClick={onClose}>
            <X size={17} aria-hidden="true" />
          </button>
        </div>
        <div className="rowline">
          <input className="field num" data-testid="share-link" aria-label="Link to this view" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
          <button ref={first} type="button" className="btn" data-testid="share-copy" onClick={copy}>
            {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
            <span>{plain.shareCopy}</span>
          </button>
        </div>
        <label>
          {plain.shareEmail}
          <span className="rowline">
            <input
              className="field"
              data-testid="share-email"
              type="email"
              inputMode="email"
              autoComplete="off"
              placeholder="name@example.com"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !tooLong && !busy) void send();
              }}
            />
            <button type="button" className="btn btn-primary" data-testid="share-send" disabled={tooLong || busy} onClick={send}>
              <Send size={15} aria-hidden="true" />
              <span>{plain.shareSend}</span>
            </button>
          </span>
        </label>
        <p className="status" data-testid="share-status" role="status" aria-live="polite">
          {tooLong ? plain.shareTooLong : status}
        </p>
        {privatePreview && <p className="hint">{plain.sharePreview}</p>}
      </div>
    </div>
  );
}
