"""Report template registry (PROJECT_PLAN 3.14).

Each template is declared in code with the data model it accepts and sample data. Rendering uses a
sandboxed Jinja2 environment with autoescape and strict undefined variables: a template that uses an
unknown variable fails at save/test time, never at customer download time. The rendered HTML must pass
`check_template_html` (accessibility) before any file is produced. Every generated report records the
template version id so it can be reproduced.

Today the templates are files in this package (reviewed like code). Admin-editable, versioned database
templates with preview and two-person approval are the next step; this registry is the interface they will
plug into (`render_html` takes the template key and a validated data object)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import BaseModel

from .pdf import ReportTemplateError, check_template_html

TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = ImmutableSandboxedEnvironment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class TemplateDef:
    key: str
    version: int
    filename: str
    model: type[BaseModel]

    @property
    def version_id(self) -> str:
        """`audit_report@v1+3fa9c2d1`: the version plus a hash of the template and its base file."""
        h = hashlib.sha256()
        for name in (self.filename, "_base.html.j2"):
            h.update((TEMPLATE_DIR / name).read_bytes())
        return f"{self.key}@v{self.version}+{h.hexdigest()[:8]}"


TEMPLATES: dict[str, TemplateDef] = {}


def register(t: TemplateDef) -> TemplateDef:
    TEMPLATES[t.key] = t
    return t


def render_html(key: str, data: BaseModel) -> str:
    t = TEMPLATES[key]
    if not isinstance(data, t.model):
        raise TypeError(f"{key} needs {t.model.__name__}, got {type(data).__name__}")
    html = _env.get_template(t.filename).render(d=data)
    if problems := check_template_html(html):
        raise ReportTemplateError(problems)
    return html


from .data import AuditReportData  # noqa: E402  (registered after the class definitions above)

register(TemplateDef("audit_report", 1, "audit_report.html.j2", AuditReportData))

from .vpat import VpatDoc  # noqa: E402

register(TemplateDef("vpat", 1, "vpat.html.j2", VpatDoc))
