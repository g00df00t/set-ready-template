"use client";

import { CSSProperties, KeyboardEvent, useId } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onBlur?: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLInputElement>) => void;
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
  placeholder?: string;
  // For callers that pair the field with a visible <label htmlFor>, rather than
  // relying on the aria-label alone.
  id?: string;
  // Named call times offered as a dropdown. A <datalist> rather than a <select>
  // because the field still has to take a typed clock time — the list is a hint,
  // not a constraint. Without it nobody discovers that "Own Call" is accepted.
  suggestions?: string[];
  // Why this value was refused, shown under the field and reflected through
  // aria-invalid. The backend already writes a usable sentence (see
  // backend/time_utils.py) — pass it straight through rather than restating it,
  // so the field names the offending text and the formats that would work.
  error?: string | null;
  // Float the message over what's below instead of reflowing it — for fields in
  // a dense table, where growing the row shifts every row under it. The value is
  // which edge to anchor to: "right" for a field sitting near the right edge of
  // its container, where a left-anchored box would run off it.
  floatError?: "left" | "right";
}

export function TimeInput({ value, onChange, onBlur, onKeyDown, className = "", style, ariaLabel = "Time", placeholder = "8:00 AM", id, suggestions, error, floatError }: Props) {
  // Stable per-field id so two fields on one page don't share a list.
  const listId = suggestions?.length ? `times-${(id || ariaLabel).replace(/\W+/g, "-")}` : undefined;
  const errorId = `${useId()}-error`;
  return (
    <>
    <input
      type="text"
      id={id}
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      className={`field-input ${className}`}
      style={style}
      list={listId}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
    />
    {listId && (
      <datalist id={listId}>
        {suggestions!.map((s) => <option key={s} value={s} />)}
      </datalist>
    )}
    {error && (
      // role="alert" so it's announced when it appears — a screen-reader user
      // has already moved on to the next field by the time the save comes back.
      <p id={errorId} role="alert" className={`field-error${floatError ? ` field-error--float field-error--float-${floatError}` : ""}`}>
        {error}
      </p>
    )}
    </>
  );
}
