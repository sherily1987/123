(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.LeagueHitRates = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function rate(hit, n) {
    return n ? Math.round(hit / n * 1000) / 10 : null;
  }

  function stats(matches, predicate) {
    const eligible = matches.filter(predicate);
    const hit = eligible.filter(match => match.hit).length;
    return { hit, n: eligible.length, rate: rate(hit, eligible.length) };
  }

  function buildLeagueHitRates(history) {
    const sections = (history && history.sections) || [];
    const leagues = {};
    sections.forEach(section => (section.matches || []).filter(match => match.settled).forEach(match => {
      const league = match.league || "未标注";
      (leagues[league] || (leagues[league] = [])).push(match);
    }));
    const rows = Object.keys(leagues).map(league => {
      const matches = leagues[league];
      const quant = stats(matches, () => true);
      const llmEligible = matches.filter(match => match.llm_scored);
      const llmHit = llmEligible.filter(match => match.llm_hit).length;
      return {
        league,
        quant,
        llm: { hit: llmHit, n: llmEligible.length, rate: rate(llmHit, llmEligible.length) },
      };
    });
    rows.sort((left, right) =>
      right.quant.rate - left.quant.rate || right.quant.n - left.quant.n || left.league.localeCompare(right.league, "zh-CN")
    );
    return rows.map((row, index) => ({ rank: index + 1, ...row }));
  }

  return { buildLeagueHitRates };
});
