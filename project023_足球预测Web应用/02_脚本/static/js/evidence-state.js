function uniqueText(values = []) {
  return [...new Set(values.map((value) => {
    if (value && typeof value === "object") {
      return String(value.field || value.key || value.reason || JSON.stringify(value));
    }
    return String(value);
  }).filter(Boolean))];
}

function fallbackGaps(lights) {
  if (!lights) return ["全部证据未采集"];
  const gaps = [];
  if (lights.form === "missing") gaps.push("近5场");
  if (["not_written", "not_collected", "conflict"].includes(lights.lineup)) gaps.push("首发");
  if (lights.injury === "none") gaps.push("伤停");
  return gaps;
}

function canonicalRefs(refs) {
  if (Array.isArray(refs)) return uniqueText(refs);
  if (!refs || typeof refs !== "object") return [];
  return uniqueText(Object.values(refs).filter(Boolean));
}

function fallbackConflicts(match) {
  const conflicts = [];
  if (match.lights?.lineup === "conflict") conflicts.push("首发来源冲突");
  if (match.identity_conflict || match.identity?.conflict || match.identity?.status === "CONFLICT") {
    conflicts.push("比赛身份冲突");
  }
  return conflicts;
}

export function normalizeEvidence(match = {}) {
  const llm = match.llm || {};
  const explicitGaps = Array.isArray(llm.evidence_missing_fields);
  const explicitChain = Array.isArray(llm.evidence_chain_fields);
  const explicitConflicts = Array.isArray(llm.evidence_conflicts);
  const gaps = explicitGaps ? uniqueText(llm.evidence_missing_fields) : fallbackGaps(match.lights);
  const conflicts = uniqueText([
    ...(explicitConflicts ? llm.evidence_conflicts : fallbackConflicts(match)),
    ...((match.identity_conflict || match.identity?.conflict || match.identity?.status === "CONFLICT")
      ? ["比赛身份冲突"] : []),
  ]);
  const refs = canonicalRefs(llm.evidence_refs);
  const canonicalStatus = llm.evidence_status ?? null;
  const normalizedCanonical = String(canonicalStatus || "").toUpperCase();
  const hasCanonicalMetadata = explicitGaps || explicitChain || explicitConflicts
    || canonicalStatus !== null || llm.evidence_collected_at != null
    || llm.evidence_age_minutes != null || refs.length > 0;
  const isCollected = Boolean(match.lights || llm.evidence_file || hasCanonicalMetadata);
  let status;
  if (conflicts.length) status = "冲突";
  else if (explicitGaps) status = gaps.length ? "有缺口" : "完整";
  else if (["OK", "VALID", "COMPLETE", "AVAILABLE", "FRESH"].includes(normalizedCanonical)) status = "完整";
  else if (["GAP", "MISSING", "PARTIAL", "CONFLICT"].includes(normalizedCanonical)) status = "有缺口";
  else if (!isCollected) status = "未采集";
  else status = gaps.length ? "有缺口" : "完整";

  let sourceCount;
  if (explicitChain) sourceCount = llm.evidence_chain_fields.length;
  else if (refs.length) sourceCount = refs.length;
  else if (match.lights) sourceCount = [
    match.lights.form !== "missing",
    match.lights.lineup === "two_source",
    match.lights.injury !== "none",
  ].filter(Boolean).length;
  else sourceCount = 0;

  return {
    status,
    canonicalStatus,
    gaps,
    conflicts,
    sourceCount,
    collectedAt: llm.evidence_collected_at ?? llm.collected_at ?? null,
    ageMinutes: Number.isFinite(Number(llm.evidence_age_minutes))
      && llm.evidence_age_minutes !== null && llm.evidence_age_minutes !== ""
      ? Number(llm.evidence_age_minutes) : null,
    refs,
  };
}

export function evidenceHasGap(match = {}) {
  const state = normalizeEvidence(match);
  return state.status === "未采集" || state.status === "冲突" || state.gaps.length > 0;
}
