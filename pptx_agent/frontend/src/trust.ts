const NEWS = new Set([
  "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
  "wsj.com", "washingtonpost.com", "ft.com", "bloomberg.com",
  "theguardian.com", "economist.com", "npr.org", "cnn.com", "cnbc.com",
  "forbes.com", "axios.com", "politico.com", "aljazeera.com",
  "techcrunch.com", "wired.com", "theverge.com", "arstechnica.com",
  "msn.com", "yahoo.com",
]);
const REFERENCE = new Set(["wikipedia.org", "britannica.com", "stackoverflow.com"]);
const ACADEMIC = new Set([
  "arxiv.org", "scholar.google.com", "semanticscholar.org",
  "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
]);
const SOCIAL = new Set([
  "twitter.com", "x.com", "facebook.com", "reddit.com", "linkedin.com",
  "instagram.com", "tiktok.com", "youtube.com",
]);

export function trustTierFromUrl(url: string): string {
  if (!url) return "unknown";
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "unknown";
  }
  if (host.endsWith(".gov") || host === "gov") return "gov";
  if (host.endsWith(".edu")) return "edu";
  if (matches(host, ACADEMIC)) return "academic";
  if (matches(host, NEWS)) return "news";
  if (matches(host, REFERENCE)) return "reference";
  if (matches(host, SOCIAL)) return "social";
  if (host.includes("blog") || host.includes("medium.com") || host.includes("substack.com")) {
    return "blog";
  }
  return "unknown";
}

function matches(host: string, set: Set<string>): boolean {
  if (set.has(host)) return true;
  for (const item of set) {
    if (host.endsWith("." + item)) return true;
  }
  return false;
}
