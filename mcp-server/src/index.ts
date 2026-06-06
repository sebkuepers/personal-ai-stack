import { McpAgent } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerGetUsedCategories } from "./tools/getUsedCategories.js";

export interface Env {
  /** Notion internal-integration token — reads the CRM database schema. */
  NOTION_TOKEN?: string;
  /** Notion API version; defaults to 2025-09-03. */
  NOTION_VERSION?: string;
  /** Durable Object namespace backing each MCP session. */
  MCP_OBJECT: DurableObjectNamespace;
}

/**
 * Personal CRM MCP server.
 *
 * Registered with Mistral as a custom connector; once attached to an agent the
 * model auto-discovers these tools and Mistral executes them server-side.
 * Add new tools by creating a file in src/tools/ and registering it in init().
 */
export class CrmMcp extends McpAgent<Env> {
  server = new McpServer({ name: "personal-crm", version: "0.1.0" });

  async init(): Promise<void> {
    registerGetUsedCategories(this.server, this.env);
  }
}

const SERVE_OPTS = { binding: "MCP_OBJECT" } as const;

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const { pathname } = new URL(request.url);

    if (pathname === "/mcp") {
      return CrmMcp.serve("/mcp", SERVE_OPTS).fetch(request, env, ctx);
    }
    if (pathname === "/sse" || pathname === "/sse/message") {
      return CrmMcp.serveSSE("/sse", SERVE_OPTS).fetch(request, env, ctx);
    }
    if (pathname === "/") {
      return new Response(
        "personal-crm MCP server — connect at /mcp (Streamable HTTP) or /sse.\n",
        { headers: { "content-type": "text/plain" } },
      );
    }
    return new Response("Not found", { status: 404 });
  },
};
