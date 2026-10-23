import type { StepModel } from "@/hooks/useStepModel";
import { cn } from "@/lib/utils";

/**
 * A model dropdown for one step, with the recommended model marked and
 * the reason for the recommendation underneath.
 */
export function ModelPicker({
  choice,
  label = "Model",
  disabled = false,
  className,
}: {
  choice: StepModel;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  const { model, options, info } = choice;
  if (!model || !info) return null;
  const recommended = options.find((o) => o.id === info.recommended);
  return (
    <div className={cn("min-w-0", className)}>
      <label className="inline-flex flex-wrap items-center gap-2 text-xs text-ink-400">
        <span>{label}</span>
        <select
          value={model}
          disabled={disabled}
          onChange={(e) => choice.setModel(e.target.value)}
          className={cn(
            "h-8 rounded-lg border border-ink-700 bg-ink-900 px-2 text-[12.5px] text-ink-100",
            "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent",
            "disabled:opacity-60",
          )}
        >
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
              {o.id === info.recommended ? " (recommended)" : ""}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-1 text-[11px] leading-snug text-ink-500">
        {model === info.recommended
          ? info.note
          : `Recommended: ${recommended?.label ?? info.recommended}. ${info.note}`}
      </p>
    </div>
  );
}
