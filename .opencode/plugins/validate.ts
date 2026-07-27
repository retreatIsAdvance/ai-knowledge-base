import type { Plugin, PluginInput, PluginOptions } from "@opencode-ai/plugin";

const ARTICLES_GLOB = /(?:^|\/)knowledge\/articles\/[^/]+\.json$/;

const plugin: Plugin = async (input: PluginInput, _options?: PluginOptions) => {
  const { $ } = input;

  return {
    async "tool.execute.after"(hookInput, _output) {
      const { tool, args } = hookInput;
      if (tool !== "write" && tool !== "edit") return;

      const filePath: string | undefined = args?.file_path ?? args?.filePath;
      if (!filePath || !ARTICLES_GLOB.test(filePath)) return;

      console.log(`[validate] Validating: ${filePath}`);

      try {
        const validateResult = await $`python3 hooks/validate_json.py ${filePath}`.nothrow();

        const vstdout = validateResult.stdout.toString().trim();
        const vstderr = validateResult.stderr.toString().trim();

        if (vstdout) console.log(`[validate] ${vstdout}`);
        if (vstderr) console.error(`[validate] ${vstderr}`);

        if (validateResult.exitCode === 0) {
          const qualityResult = await $`python3 hooks/check_quality.py ${filePath}`.nothrow();
          const qstdout = qualityResult.stdout.toString().trim();
          const qstderr = qualityResult.stderr.toString().trim();

          if (qstdout) console.log(`[quality] ${qstdout}`);
          if (qstderr) console.error(`[quality] ${qstderr}`);
        }
      } catch (err) {
        console.error("[validate] Unexpected error during validation:", err);
      }
    },
  };
};

export const server = plugin;
