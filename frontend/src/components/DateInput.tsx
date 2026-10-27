"use client";

import { CSSProperties, forwardRef, useImperativeHandle, useRef } from "react";

interface Props {
  value: string;                       // ISO yyyy-mm-dd, what <input type="date"> speaks
  onChange: (v: string) => void;
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
  id?: string;
  min?: string;
  max?: string;
  required?: boolean;
}

//: Imperative handle for a caller that needs to drive the field itself —
//: today, only the deal-memo date-range picker, which opens the "To" field's
//: calendar the moment "From" is picked (the Alaska/Delta departure-then-
//: return pattern). Everyone else just uses value/onChange.
export interface DateInputHandle {
  openPicker: () => void;
  focus: () => void;
}

// A date field that opens its calendar when you click the field — not only when
// you hit the ~16px calendar glyph at the right edge. Chrome and Safari focus
// the text on a click and leave the picker shut, so the control reads as "type
// mm/dd/yyyy" even though a picker was there the whole time. Typing still works
// for anyone who prefers it; showPicker() only adds the click affordance.
export const DateInput = forwardRef<DateInputHandle, Props>(function DateInput(
  { value, onChange, className = "", style, ariaLabel = "Date", id, min, max, required },
  handleRef,
) {
  const ref = useRef<HTMLInputElement>(null);

  function openPicker() {
    const el = ref.current;
    // Feature-detect: Firefox < 101 and older Safari have no showPicker, and it
    // throws without user activation. Either way the native field is unharmed.
    if (!el || typeof el.showPicker !== "function") return;
    try {
      el.showPicker();
    } catch {
      /* no user activation, or the browser declined — typing still works */
    }
  }

  useImperativeHandle(handleRef, () => ({
    openPicker,
    focus: () => ref.current?.focus(),
  }));

  return (
    <input
      ref={ref}
      type="date"
      id={id}
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onClick={openPicker}
      min={min}
      max={max}
      required={required}
      className={`field-input date-input ${className}`}
      style={style}
    />
  );
});
