import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { CATEGORIES, SUB_CATEGORIES, NOTION_INTERACTIONS_DATA_SOURCE } from "../crm.js";
import type { Env } from "../index.js";

interface CategoryResult {
  source: "notion" | "config";
  categories: string[];
  sub_categories: string[];
  note?: string;
}

/**
 * Read the live "Category" and "Sub-Category" select options from the Notion
 * Interactions data source. Falls back to the canonical vocabulary in
 * shared/crm.json when no token is configured or the call fails.
 */
async function fetchUsedCategories(env: Env): Promise<CategoryResult> {
  const fallback: CategoryResult = {
    source: "config",
    categories: CATEGORIES,
    sub_categories: SUB_CATEGORIES,
  };

  if (!env.NOTION_TOKEN) {
    fallback.note = "NOTION_TOKEN not set — returning the canonical vocabulary from shared/crm.json.";
    return fallback;
  }

  const version = env.NOTION_VERSION || "2025-09-03";
  const headers = {
    Authorization: `Bearer ${env.NOTION_TOKEN}`,
    "Notion-Version": version,
  };

  // The IDs in crm.json are data-source (collection) UUIDs. Try the data_sources
  // endpoint first (current API), then fall back to the legacy databases endpoint.
  const id = NOTION_INTERACTIONS_DATA_SOURCE;
  const urls = [
    `https://api.notion.com/v1/data_sources/${id}`,
    `https://api.notion.com/v1/databases/${id}`,
  ];

  for (const url of urls) {
    try {
      const res = await fetch(url, { headers });
      if (!res.ok) continue;
      const body = (await res.json()) as { properties?: Record<string, NotionProperty> };
      const props = body.properties ?? {};
      const categories = selectOptions(props, "Category");
      const subCategories = selectOptions(props, "Sub-Category");
      if (categories.length || subCategories.length) {
        return { source: "notion", categories, sub_categories: subCategories };
      }
    } catch {
      // try the next URL / fall through to fallback
    }
  }

  fallback.note = "Could not read the live Notion schema — returning the canonical vocabulary.";
  return fallback;
}

interface NotionProperty {
  type?: string;
  select?: { options?: { name?: string }[] };
}

function selectOptions(props: Record<string, NotionProperty>, name: string): string[] {
  const prop = props[name];
  if (!prop || prop.type !== "select" || !prop.select?.options) return [];
  return prop.select.options.map((o) => o.name).filter((n): n is string => Boolean(n));
}

export function registerGetUsedCategories(server: McpServer, env: Env): void {
  server.registerTool(
    "get_used_categories",
    {
      title: "Get the CRM categories currently in use",
      description:
        "Returns the interaction categories and sub-categories currently defined in the personal " +
        "CRM. Call this before classifying so you reuse an existing category rather than inventing " +
        "a near-duplicate; only propose a new category when none of these fit. Source is the live " +
        "Notion Interactions schema when available, otherwise the canonical vocabulary.",
      inputSchema: {},
    },
    async () => {
      const result = await fetchUsedCategories(env);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );
}
