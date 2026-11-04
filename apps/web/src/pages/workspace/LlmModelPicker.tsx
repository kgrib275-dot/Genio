// v0.6: 기본 모델 고르기(제공사의 대표 모델 + 연결 테스트로 불러온 실제 모델) + 직접 입력
import { Input, Select } from "@/components/ui/input";

export interface ModelOption {
  model: string;
  label: string;
  vision?: boolean;
}

const CUSTOM = "__custom__";

export function LlmModelPicker({
  id,
  value,
  onChange,
  presetModels,
  fetched,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  presetModels: ModelOption[];
  fetched: ModelOption[] | null;
}) {
  const options: ModelOption[] = fetched?.length
    ? [
        ...fetched.map((m) => ({
          ...m,
          vision: presetModels.find((p) => p.model === m.model)?.vision,
        })),
      ]
    : presetModels;
  const known = options.some((o) => o.model === value);
  const custom = !known && value !== "" ? true : options.length === 0;
  return (
    <div className="space-y-2">
      {options.length > 0 && (
        <Select
          id={id}
          value={known ? value : CUSTOM}
          onChange={(e) => onChange(e.target.value === CUSTOM ? "" : e.target.value)}
        >
          <optgroup
            label={fetched?.length ? `이 키로 쓸 수 있는 모델 ${fetched.length}개` : "대표 모델"}
          >
            {options.map((m) => (
              <option key={m.model} value={m.model}>
                {m.label && m.label !== m.model ? `${m.label} · ${m.model}` : m.model}
                {m.vision ? " · 이미지" : ""}
              </option>
            ))}
          </optgroup>
          <option value={CUSTOM}>직접 입력…</option>
        </Select>
      )}
      {(custom || !known) && (
        <Input
          id={options.length ? `${id}-custom` : id}
          required
          placeholder="모델 이름(예: 배포 이름이나 새 모델)"
          aria-label="모델 이름 직접 입력"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
