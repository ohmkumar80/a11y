/** Just enough of OpenAPI 3 to render a readable reference: no external renderer, so the page is ours to make accessible. */
export interface Schema { $ref?: string; type?: string; format?: string; description?: string; properties?: Record<string, Schema>; required?: string[]; items?: Schema; anyOf?: Schema[]; enum?: string[]; example?: unknown; title?: string; default?: unknown; pattern?: string; minimum?: number; maximum?: number; maxLength?: number }
export interface Parameter { name: string; in: string; required?: boolean; description?: string; schema?: Schema }
export interface Operation {
  operationId: string; summary: string; description: string; tags?: string[]; parameters?: Parameter[];
  requestBody?: { required?: boolean; content: Record<string, { schema: Schema }> };
  responses: Record<string, { description?: string; content?: Record<string, { schema?: Schema }> }>;
  "x-required-scope"?: string;
}
export interface Spec {
  info: { title: string; version: string; description: string };
  servers?: Array<{ url: string }>;
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, Schema> };
  tags?: Array<{ name: string }>;
}
export interface Field { name: string; type: string; required: boolean; description: string }

export const refName = (s: Schema | undefined) => s?.$ref?.split("/").pop();
export function resolve(spec: Spec, s: Schema | undefined): Schema | undefined {
  const n = refName(s);
  return n ? spec.components.schemas[n] : s;
}
export function typeOf(spec: Spec, s: Schema | undefined): string {
  if (!s) return "any";
  if (s.$ref) return refName(s)!;
  if (s.anyOf) return s.anyOf.map((x) => typeOf(spec, x)).filter((t) => t !== "null").join(" or ") || "null";
  if (s.type === "array") return `list of ${typeOf(spec, s.items)}`;
  if (s.enum) return `one of ${s.enum.join(", ")}`;
  return `${s.type ?? "any"}${s.format ? ` (${s.format})` : ""}`;
}
export function fields(spec: Spec, s: Schema | undefined): Field[] {
  const r = resolve(spec, s);
  if (!r?.properties) return [];
  return Object.entries(r.properties).map(([name, p]) => ({ name, type: typeOf(spec, p), required: !!r.required?.includes(name), description: (resolve(spec, p)?.description ?? p.description ?? "").trim() }));
}
export function exampleOf(spec: Spec, s: Schema | undefined): unknown {
  const r = resolve(spec, s);
  return r?.example;
}
export function curl(base: string, method: string, path: string, op: Operation, body: unknown): string {
  const p = path.replace(/\{(\w+)\}/g, (_m, n: string) => `<${n}>`);
  const lines = [`curl ${method !== "get" ? `-X ${method.toUpperCase()} ` : ""}"${base}${p}"`, `  -H "Authorization: Bearer $A11Y_API_KEY"`];
  if (op.parameters?.some((x) => x.name === "Idempotency-Key")) lines.push(`  -H "Idempotency-Key: $(uuidgen)"`);
  if (body !== undefined) { lines.push(`  -H "Content-Type: application/json"`, `  -d '${JSON.stringify(body)}'`); }
  return lines.join(" \\\n");
}
/** Tiny, safe formatter for text we write or admins write: paragraphs, **bold**, `code` and [links](https://...). Only https
 *  links are recognised; anything else stays plain text. Never injects HTML. */
export type Piece = { kind: "text" | "code" | "bold"; value: string } | { kind: "link"; value: string; href: string };
export function inline(text: string): Piece[] {
  const out: Piece[] = [];
  for (const part of text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https:\/\/[^\s)]+\))/g)) {
    if (!part) continue;
    const link = /^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)$/.exec(part);
    if (link) out.push({ kind: "link", value: link[1]!, href: link[2]! });
    else if (part.startsWith("`")) out.push({ kind: "code", value: part.slice(1, -1) });
    else if (part.startsWith("**")) out.push({ kind: "bold", value: part.slice(2, -2) });
    else out.push({ kind: "text", value: part });
  }
  return out;
}
