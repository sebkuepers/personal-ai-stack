// Single import point for the monorepo source of truth (../../shared/crm.json).
// Bundled into the Worker at build time by esbuild/wrangler.
import crm from "../../shared/crm.json";

export const NOTION_INTERACTIONS_DATA_SOURCE: string = crm.notion.databases.interactions;
export const CATEGORIES: string[] = crm.vocab.categories;
export const SUB_CATEGORIES: string[] = crm.vocab.sub_categories;

export default crm;
