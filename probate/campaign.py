"""Die Unterschrift, in DataHubs eigener Freigabe-Oberflaeche.

Drei gemessene Fallen (2026-08-04, Gegenmessung gegen 28080 abgeschlossen):
- submitFormPrompt nimmt das Asset als EIGENES erstes Argument, nicht im input
- verifyForm ist autorisationsgebunden: nicht zugewiesen -> 403
- verifyForm PRUEFT ZWEI VORBEDINGUNGEN (FormService.java:920, VerifyFormResolver.java):
  (1) das Formular braucht actors: { owners: true } ODER eine explizite users/groups-Liste,
  (2) der HANDELNDE muss Eigentuemer der Zielentitaet sein. Ohne Token laeuft probate als
  urn:li:corpuser:__datahub_system -- NICHT urn:li:corpuser:datahub. Fehlt eine der beiden
  Vorbedingungen: 403 "form is not assigned to user", keine Ausnahme, kein anderer Fehlertext.
  create_campaign setzt actors:{owners:true}; ensure_owner() deckt die zweite Vorbedingung ab
  und MUSS vor assign()/verify() pro Ziel-Dataset aufgerufen werden.
"""

from __future__ import annotations


class NoEvidenceError(RuntimeError):
    """Probate verifiziert nicht, was es nicht belegen kann."""


def create_campaign(wb, form_id: str, name: str, prompts: list[tuple[str, str]]) -> str:
    """`prompts` ist eine Liste aus (prompt_id, structured_property_urn).

    Live-Fund (2026-08-06): ein Prompt vom Typ STRUCTURED_PROPERTY ohne
    eigene structuredPropertyParams wird von createForm mit HTTP 400
    abgelehnt ("no structured property params") -- die Property muss
    schon beim ANLEGEN des Formulars benannt werden, nicht erst bei
    submitFormPrompt. Achtung, andere Feldform als bei submitFormPrompt
    (Falle 6 aus der Forms-Gegenmessung vom 04.08.): createForm will
    structuredPropertyParams: { urn }, submitFormPrompt dagegen
    structuredPropertyParams: { structuredPropertyUrn, values }.
    """
    prompt_defs = ", ".join(
        f'{{ id: "{pid}", title: "Umbau bestaetigt?", type: STRUCTURED_PROPERTY, '
        f'required: true, structuredPropertyParams: {{ urn: "{prop_urn}" }} }}'
        for pid, prop_urn in prompts
    )
    # actors: { owners: true } ist PFLICHT -- ohne das lehnt verifyForm() spaeter mit
    # 403 ab, egal wie sorgfaeltig assign()/autofill() liefen (gemessen 2026-08-04).
    q = f'''mutation {{ createForm(input: {{
        id: "{form_id}", name: "{name}", type: VERIFICATION, prompts: [{prompt_defs}],
        actors: {{ owners: true }}
      }}) {{ urn }} }}'''
    wb.mutation("createForm", q)
    return f"urn:li:form:{form_id}"


def ensure_owner(wb, entity_type: str, urn: str, actor: str) -> bool:
    """Zweite Vorbedingung fuer verifyForm(): der Handelnde muss Owner
    der Zielentitaet sein. Additiv -- bestehende Owner bleiben erhalten,
    `actor` wird nur ergaenzt, wenn er noch fehlt. Gibt False zurueck
    (kein Schreibvorgang), wenn actor bereits Owner ist.

    Ownership.pdl (Quelle gelesen, github.com/datahub-project/datahub):
    owners ist Pflichtfeld (array[Owner]), Owner.owner + Owner.type sind
    Pflicht. lastModified hat einen Default und wird hier weggelassen.
    """
    existing = wb.gms.get_aspect(entity_type, urn, "ownership")
    owners = ((existing or {}).get("value") or {}).get("owners", [])
    if any(o.get("owner") == actor for o in owners):
        return False
    owners = owners + [{"owner": actor, "type": "TECHNICAL_OWNER"}]
    wb.aspect(entity_type, urn, "ownership", {"owners": owners})
    return True


def assign(wb, form_urn: str, entity_urns: list[str]):
    urns = ", ".join(f'"{u}"' for u in entity_urns)
    q = f'''mutation {{ batchAssignForm(input: {{
        formUrn: "{form_urn}", entityUrns: [{urns}] }}) }}'''
    return wb.mutation("batchAssignForm", q)


def autofill(wb, form_urn: str, entity_urn: str, prompt_id: str,
             property_urn: str, value: str, evidence: dict):
    if not evidence:
        raise NoEvidenceError("Vorbefuellen ohne Beleg ist eine Behauptung.")
    # Live-Fund (2026-08-06): submitFormPrompt liefert Boolean direkt, keine
    # Subselektion erlaubt. { success } (wie im Plantext) scheitert mit
    # "SubselectionNotAllowed" -- derselbe Schema-Bautyp wie verifyForm.
    q = f'''mutation {{ submitFormPrompt(
        urn: "{entity_urn}",
        input: {{ formUrn: "{form_urn}", promptId: "{prompt_id}",
                  type: STRUCTURED_PROPERTY,
                  structuredPropertyParams: {{ structuredPropertyUrn: "{property_urn}",
                                               values: [{{ stringValue: "{value}" }}] }} }}
      ) }}'''
    return wb.mutation("submitFormPrompt", q)


def verify(wb, form_urn: str, entity_urn: str, evidence: dict):
    if not evidence:
        raise NoEvidenceError(
            "verifyForm ohne Beleg waere genau die Unterschrift, die dieses "
            "Werkzeug verhindern soll."
        )
    q = f'''mutation {{ verifyForm(input: {{
        formUrn: "{form_urn}", entityUrn: "{entity_urn}" }}) }}'''
    return wb.mutation("verifyForm", q)
