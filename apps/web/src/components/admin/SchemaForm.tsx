"use client";

/**
 * Generates an accessible form from a Pydantic JSON Schema (PROJECT_PLAN 3.11.1: the admin UI
 * is generated from the settings registry, so a new setting needs no new screen).
 *
 * Supported: objects, strings, numbers, booleans, enums/Literals, nullable values, secrets
 * (write-only), arrays of objects (add/remove), arrays of enums (checkbox group), arrays of
 * strings/numbers (comma separated) and string maps ("key=value, key=value").
 * Every control is a labelled React Aria component; nothing is drag-only.
 */

import { Button, Checkbox, Select, TextField } from "@a11y/ui";

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export interface Schema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  enum?: Array<string | number>;
  const?: Json;
  anyOf?: Schema[];
  $ref?: string;
  $defs?: Record<string, Schema>;
  default?: Json;
  format?: string;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  additionalProperties?: Schema | boolean;
}

const isObj = (v: unknown): v is { [k: string]: Json } => typeof v === "object" && v !== null && !Array.isArray(v);
const pretty = (k: string) => k.replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase());

function resolve(s: Schema, root: Schema): { schema: Schema; nullable: boolean; secret: boolean } {
  let nullable = false;
  let cur = s;
  if (cur.anyOf) {
    const nonNull = cur.anyOf.filter((x) => x.type !== "null");
    nullable = nonNull.length !== cur.anyOf.length;
    cur = { ...cur, ...nonNull[0], anyOf: undefined, description: s.description ?? nonNull[0]?.description };
  }
  let secret = false;
  if (cur.$ref) {
    secret = cur.$ref.endsWith("/Secret");
    const target = root.$defs?.[cur.$ref.split("/").pop() ?? ""] ?? {};
    cur = { ...target, description: cur.description ?? target.description, title: cur.title };
  }
  return { schema: cur, nullable, secret };
}

/** A fresh value for "Add item" and for settings that have never been set. */
export function defaultFor(s: Schema, root: Schema): Json {
  const { schema, nullable, secret } = resolve(s, root);
  if (secret) return { $secret: true } as Json;
  if (schema.default !== undefined && !isObj(schema.default)) return schema.default;
  if (schema.const !== undefined) return schema.const;
  if (schema.properties) {
    const o: { [k: string]: Json } = {};
    for (const [k, p] of Object.entries(schema.properties)) o[k] = defaultFor(p, root);
    return o;
  }
  if (nullable) return null;
  switch (schema.type) {
    case "array": return [];
    case "boolean": return false;
    case "integer": case "number": return schema.minimum ?? 0;
    case "object": return {};
    default: return schema.enum ? (schema.enum[0] ?? "") : "";
  }
}

/** Strip display-only fields before sending: secrets carry plaintext only. */
export function prepare(v: Json): Json {
  if (Array.isArray(v)) return v.map(prepare);
  if (isObj(v)) {
    if (v.$secret === true) return v.plaintext ? { $secret: true, plaintext: v.plaintext } : { $secret: true };
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, prepare(x)]));
  }
  return v;
}

interface FieldProps {
  schema: Schema;
  root: Schema;
  value: Json;
  onChange: (v: Json) => void;
  label: string;
  id: string;
  /** Items in an array get a legend like "Provider 2"; top level has none. */
  nested?: boolean;
}

function Field({ schema: raw, root, value, onChange, label, id, nested }: FieldProps) {
  const { schema, nullable, secret } = resolve(raw, root);
  const description = raw.description ?? schema.description;

  if (secret) {
    const sv = isObj(value) ? value : {};
    const hint = sv.set ? `Currently set${sv.hint ? ` (ends in ${String(sv.hint).replace(/•/g, "")})` : ""}. Leave blank to keep it.` : "Not set yet.";
    return (
      <TextField id={id} label={label} type="password" autoComplete="off" description={`${hint} It is never shown again after saving.`}
        value={typeof sv.plaintext === "string" ? sv.plaintext : ""} onChange={(p) => onChange({ ...sv, $secret: true, plaintext: p })} />
    );
  }

  if (schema.const !== undefined) {
    return <p><span className="font-semibold">{label}:</span> {String(schema.const)} (fixed)</p>;
  }

  if (schema.properties) {
    const obj = isObj(value) ? value : {};
    const body = Object.entries(schema.properties).map(([k, p]) => (
      <Field key={k} schema={p} root={root} label={pretty(k)} id={`${id}-${k}`} value={obj[k] ?? null} onChange={(nv) => onChange({ ...obj, [k]: nv })} />
    ));
    if (!nested) return <div className="flex flex-col gap-4">{body}</div>;
    return (
      <fieldset className="flex flex-col gap-4 rounded-md border-2 border-border-subtle p-4">
        <legend className="px-1 font-semibold">{label}</legend>
        {body}
      </fieldset>
    );
  }

  switch (schema.type) {
    case "boolean":
      return <Checkbox label={label} isSelected={value === true} onChange={onChange} />;

    case "integer":
    case "number": {
      const bounds = [schema.minimum !== undefined && `minimum ${schema.minimum}`, schema.maximum !== undefined && `maximum ${schema.maximum}`].filter(Boolean).join(", ");
      const range = bounds && `(${bounds})`;
      return (
        <TextField id={id} label={label} type="number" inputMode="numeric" description={[description && description.replace(/\.?$/, "."), nullable && "Leave empty for none.", range].filter(Boolean).join(" ")}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(t) => onChange(t === "" ? (nullable ? null : 0) : Number(t))} />
      );
    }

    case "string": {
      if (schema.enum) {
        return (
          <Select label={label} value={String(value ?? "")} onChange={(k) => onChange(String(k))}
            options={schema.enum.map((o) => ({ id: String(o), label: String(o) }))} />
        );
      }
      const date = schema.format === "date";
      return (
        <TextField id={id} label={label} type={date ? "date" : "text"} description={[description, nullable && "Optional."].filter(Boolean).join(" ")}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(t) => onChange(t === "" && nullable ? null : t)} />
      );
    }

    case "array": {
      const list = Array.isArray(value) ? value : [];
      const items = schema.items ?? {};
      const { schema: itemSchema } = resolve(items, root);
      if (itemSchema.properties) {
        return (
          <fieldset className="flex flex-col gap-4 rounded-md border-2 border-border-subtle p-4">
            <legend className="px-1 font-semibold">{label}</legend>
            {description && <p className="text-sm text-fg-muted">{description}</p>}
            {list.length === 0 && <p className="text-fg-muted">None yet.</p>}
            {list.map((item, i) => (
              <div key={i} className="flex flex-col gap-3">
                <Field schema={items} root={root} nested label={`${label.replace(/s$/, "")} ${i + 1}`} id={`${id}-${i}`} value={item}
                  onChange={(nv) => onChange(list.map((x, j) => (j === i ? nv : x)))} />
                <div>
                  <Button variant="secondary" onPress={() => onChange(list.filter((_, j) => j !== i))}>
                    Remove {label.replace(/s$/, "").toLowerCase()} {i + 1}
                  </Button>
                </div>
              </div>
            ))}
            <div>
              <Button variant="secondary" onPress={() => onChange([...list, defaultFor(items, root)])}>Add {label.replace(/s$/, "").toLowerCase()}</Button>
            </div>
          </fieldset>
        );
      }
      if (itemSchema.enum) {
        return (
          <fieldset className="flex flex-col gap-1">
            <legend className="font-semibold">{label}</legend>
            {itemSchema.enum.map((o) => (
              <Checkbox key={String(o)} label={String(o)} isSelected={list.includes(o)}
                onChange={(on) => onChange(on ? [...list, o] : list.filter((x) => x !== o))} />
            ))}
          </fieldset>
        );
      }
      const numeric = itemSchema.type === "integer" || itemSchema.type === "number";
      return (
        <TextField id={id} label={label} description={[description, "Separate items with commas."].filter(Boolean).join(" ")}
          value={list.join(", ")}
          onChange={(t) => onChange(t.split(",").map((x) => x.trim()).filter(Boolean).map((x) => (numeric ? Number(x) : x)))} />
      );
    }

    case "object": {
      const m = isObj(value) ? value : {};
      return (
        <TextField id={id} label={label} description={[description, "Write key=value pairs separated by commas."].filter(Boolean).join(" ")}
          value={Object.entries(m).map(([k, v]) => `${k}=${v}`).join(", ")}
          onChange={(t) => onChange(Object.fromEntries(t.split(",").map((p) => p.trim()).filter((p) => p.includes("=")).map((p) => [p.slice(0, p.indexOf("=")).trim(), p.slice(p.indexOf("=") + 1).trim()])))} />
      );
    }
    default:
      return <p className="text-fg-muted">{label}: this field type is not editable here.</p>;
  }
}

export function SchemaForm({ schema, value, onChange, idPrefix = "f" }: { schema: Schema; value: Json; onChange: (v: Json) => void; idPrefix?: string }) {
  return <Field schema={schema} root={schema} value={value} onChange={onChange} label="" id={idPrefix} />;
}
