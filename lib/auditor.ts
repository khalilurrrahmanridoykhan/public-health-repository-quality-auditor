type FileMap = Map<string, string | null>;

export const checkKeys = [
  "readme",
  "license",
  "citation",
  "dependencies",
  "reproduction",
  "tests",
  "data_dictionary",
  "provenance",
  "privacy",
  "ethics",
] as const;

export type CheckKey = (typeof checkKeys)[number];

export type AuditPolicy = {
  minimumScore: number;
  disabledChecks: CheckKey[];
  requiredFiles: string[];
  ignorePaths: string[];
  privacyTerms: string[];
};

export type Result = {
  key: CheckKey;
  title: string;
  passed: boolean;
  points: number;
  recommendation: string;
  documentationUrl: string;
};

const defaultPolicy: AuditPolicy = {
  minimumScore: 80,
  disabledChecks: [],
  requiredFiles: [],
  ignorePaths: [],
  privacyTerms: [
    "privacy",
    "de-ident",
    "anonym",
    "patient",
    "person-level",
    "sensitive data",
  ],
};

const dependencyFiles = new Set([
  "requirements.txt",
  "pyproject.toml",
  "environment.yml",
  "environment.yaml",
  "renv.lock",
  "package-lock.json",
  "poetry.lock",
  "uv.lock",
]);

const dataDictionaryFiles = new Set([
  "data_dictionary.csv",
  "data-dictionary.csv",
  "data_dictionary.md",
  "data-dictionary.md",
  "codebook.csv",
  "codebook.md",
]);

function cleanPath(value: string) {
  return value.trim().replace(/^\/+|\/+$/g, "").toLowerCase();
}

function stringList(value: unknown, key: string, warnings: string[]) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    warnings.push(`\`${key}\` must be a list of paths or check keys.`);
    return [];
  }
  return value
    .filter((item): item is string => {
      if (typeof item !== "string" || !item.trim()) {
        warnings.push(`\`${key}\` contains a non-string or empty value.`);
        return false;
      }
      return true;
    })
    .slice(0, 50);
}

export function policyFromObject(value: unknown): {
  policy: AuditPolicy;
  warnings: string[];
} {
  const warnings: string[] = [];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {
      policy: { ...defaultPolicy },
      warnings: ["Policy must be a YAML object; default policy was used."],
    };
  }
  const source = value as Record<string, unknown>;
  let minimumScore = defaultPolicy.minimumScore;
  if (source.minimum_score !== undefined) {
    if (
      typeof source.minimum_score === "number" &&
      Number.isInteger(source.minimum_score) &&
      source.minimum_score >= 0 &&
      source.minimum_score <= 100
    ) {
      minimumScore = source.minimum_score;
    } else {
      warnings.push("`minimum_score` must be an integer from 0 to 100.");
    }
  }

  const disabledChecks = stringList(
    source.disabled_checks,
    "disabled_checks",
    warnings,
  ).filter((key): key is CheckKey => {
    if ((checkKeys as readonly string[]).includes(key)) return true;
    warnings.push(`Unknown disabled check: \`${key}\`.`);
    return false;
  });
  const requiredFiles = stringList(
    source.required_files,
    "required_files",
    warnings,
  ).map(cleanPath);
  const ignorePaths = stringList(
    source.ignore_paths,
    "ignore_paths",
    warnings,
  ).map(cleanPath);
  const configuredPrivacyTerms = stringList(
    source.privacy_terms,
    "privacy_terms",
    warnings,
  ).map((term) => term.trim().toLowerCase());

  return {
    policy: {
      minimumScore,
      disabledChecks: [...new Set(disabledChecks)],
      requiredFiles: [...new Set(requiredFiles)],
      ignorePaths: [...new Set(ignorePaths)],
      privacyTerms: configuredPrivacyTerms.length
        ? [...new Set(configuredPrivacyTerms)]
        : [...defaultPolicy.privacyTerms],
    },
    warnings,
  };
}

function hasFile(paths: string[], names: Set<string>) {
  return paths.some((path) => names.has(path.split("/").at(-1) ?? ""));
}

export function audit(
  repository: string,
  files: FileMap,
  policy: AuditPolicy = defaultPolicy,
  policyWarnings: string[] = [],
) {
  const ignored = (path: string) =>
    policy.ignorePaths.some(
      (prefix) => path === prefix || path.startsWith(`${prefix}/`),
    );
  const normalized = new Map(
    [...files.entries()]
      .map(([path, content]) => [cleanPath(path), content] as const)
      .filter(([path]) => !ignored(path)),
  );
  const paths = [...normalized.keys()];
  const readme =
    normalized.get("readme.md") ?? normalized.get("readme.rst") ?? "";
  const text = readme.toLowerCase();

  const allResults: Result[] = [
    {
      key: "readme",
      title: "Project documentation",
      passed: Boolean(text.trim()),
      points: 12,
      recommendation:
        "Add a README explaining the research question, methods, data, and usage.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#project-documentation",
    },
    {
      key: "license",
      title: "License",
      passed: hasFile(
        paths,
        new Set(["license", "license.md", "license.txt", "copying"]),
      ),
      points: 10,
      recommendation:
        "Add a LICENSE and clarify whether data have separate reuse terms.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#license",
    },
    {
      key: "citation",
      title: "Machine-readable citation",
      passed: hasFile(paths, new Set(["citation.cff", "codemeta.json"])),
      points: 8,
      recommendation:
        "Add CITATION.cff with authors, title, version, and preferred citation.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#citation",
    },
    {
      key: "dependencies",
      title: "Dependency specification",
      passed: hasFile(paths, dependencyFiles),
      points: 12,
      recommendation:
        "Add a dependency or environment file with compatible version ranges.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#dependencies",
    },
    {
      key: "reproduction",
      title: "One-command reproduction",
      passed:
        hasFile(
          paths,
          new Set(["makefile", "dvc.yaml", "snakefile", "nextflow.config"]),
        ) ||
        text.includes("make reproduce") ||
        text.includes("how to reproduce"),
      points: 14,
      recommendation:
        "Provide a Makefile, workflow, or documented single command that regenerates outputs.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#reproduction",
    },
    {
      key: "tests",
      title: "Automated tests or CI",
      passed: paths.some(
        (path) =>
          path.startsWith("tests/") ||
          path.startsWith("test/") ||
          path.startsWith(".github/workflows/"),
      ),
      points: 12,
      recommendation:
        "Add tests and CI for data validation and analytical invariants.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#tests-and-ci",
    },
    {
      key: "data_dictionary",
      title: "Data dictionary or codebook",
      passed:
        hasFile(paths, dataDictionaryFiles) ||
        text.includes("data description"),
      points: 10,
      recommendation:
        "Document variables, units, missing-value conventions, and allowed values.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#data-dictionary",
    },
    {
      key: "provenance",
      title: "Data provenance",
      passed: ["data source", "data provenance", "source data"].some((term) =>
        text.includes(term),
      ),
      points: 8,
      recommendation:
        "Document each data source, access date, transformation, and license.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#data-provenance",
    },
    {
      key: "privacy",
      title: "Privacy and sensitive-data warning",
      passed: policy.privacyTerms.some((term) => text.includes(term)),
      points: 8,
      recommendation:
        "State whether data are aggregate, synthetic, de-identified, or sensitive.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#privacy",
    },
    {
      key: "ethics",
      title: "Ethics statement",
      passed: ["ethics", "irb", "institutional review", "consent"].some(
        (term) => text.includes(term),
      ),
      points: 6,
      recommendation:
        "State the ethics/IRB basis or explain why review was not required.",
      documentationUrl: "https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor#ethics",
    },
  ];
  const results = allResults.filter(
    (result) => !policy.disabledChecks.includes(result.key),
  );
  const possible = results.reduce((sum, result) => sum + result.points, 0);
  const earned = results
    .filter((result) => result.passed)
    .reduce((sum, result) => sum + result.points, 0);
  const score = possible ? Math.round((earned / possible) * 100) : 0;
  const grade =
    score >= 90
      ? "A"
      : score >= 80
        ? "B"
        : score >= 70
          ? "C"
          : score >= 60
            ? "D"
            : "F";
  const pathSet = new Set(paths);
  const missingRequiredFiles = policy.requiredFiles.filter(
    (path) => !pathSet.has(path),
  );
  const passed =
    score >= policy.minimumScore &&
    missingRequiredFiles.length === 0 &&
    policyWarnings.length === 0;

  const rows = results
    .map(
      (result) =>
        `| ${result.title} | ${result.passed ? "✅ Pass" : "❌ Needs work"} | ${result.passed ? result.points : 0}/${result.points} |`,
    )
    .join("\n");
  const recommendations =
    results
      .filter((result) => !result.passed)
      .map(
        (result) =>
          `- **${result.title}:** ${result.recommendation} [Guidance](${result.documentationUrl})`,
      )
      .join("\n") || "- All configured quality checks passed.";
  const requiredSummary = missingRequiredFiles.length
    ? missingRequiredFiles.map((path) => `- Missing required file: \`${path}\``).join("\n")
    : "- All configured required files are present.";
  const warningSummary = policyWarnings.length
    ? `\n### Policy warnings\n\n${policyWarnings.map((item) => `- ${item}`).join("\n")}\n`
    : "";

  return {
    repository,
    score,
    grade,
    passed,
    minimumScore: policy.minimumScore,
    missingRequiredFiles,
    results,
    markdown: `## Public Health Repository Quality: ${score}/100 (${grade})

Policy threshold: **${policy.minimumScore}/100** · Result: **${passed ? "Pass" : "Needs work"}**

| Check | Result | Points |
|---|---:|---:|
${rows}

### Required files

${requiredSummary}

### Recommended next steps

${recommendations}
${warningSummary}
_This automated review supports maintainers; it does not certify scientific validity, privacy compliance, or research ethics._`,
  };
}
