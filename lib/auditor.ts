type FileMap = Map<string, string | null>;

type Result = {
  title: string;
  passed: boolean;
  points: number;
  recommendation: string;
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

function hasFile(paths: string[], names: Set<string>) {
  return paths.some((path) => names.has(path.split("/").at(-1) ?? ""));
}

export function audit(repository: string, files: FileMap) {
  const paths = [...files.keys()].map((path) => path.toLowerCase());
  const readme =
    files.get("README.md") ??
    files.get("readme.md") ??
    files.get("README.rst") ??
    "";
  const text = readme.toLowerCase();

  const results: Result[] = [
    {
      title: "Project documentation",
      passed: Boolean(text.trim()),
      points: 12,
      recommendation:
        "Add a README explaining the research question, methods, data, and usage.",
    },
    {
      title: "License",
      passed: hasFile(
        paths,
        new Set(["license", "license.md", "license.txt", "copying"]),
      ),
      points: 10,
      recommendation:
        "Add a LICENSE and clarify whether data have separate reuse terms.",
    },
    {
      title: "Machine-readable citation",
      passed: hasFile(paths, new Set(["citation.cff", "codemeta.json"])),
      points: 8,
      recommendation:
        "Add CITATION.cff with authors, title, version, and preferred citation.",
    },
    {
      title: "Dependency specification",
      passed: hasFile(paths, dependencyFiles),
      points: 12,
      recommendation:
        "Add a dependency or environment file with compatible version ranges.",
    },
    {
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
    },
    {
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
    },
    {
      title: "Data dictionary or codebook",
      passed:
        hasFile(paths, dataDictionaryFiles) ||
        text.includes("data description"),
      points: 10,
      recommendation:
        "Document variables, units, missing-value conventions, and allowed values.",
    },
    {
      title: "Data provenance",
      passed: ["data source", "data provenance", "source data"].some((term) =>
        text.includes(term),
      ),
      points: 8,
      recommendation:
        "Document each data source, access date, transformation, and license.",
    },
    {
      title: "Privacy and sensitive-data warning",
      passed: [
        "privacy",
        "de-ident",
        "anonym",
        "patient",
        "person-level",
        "sensitive data",
      ].some((term) => text.includes(term)),
      points: 8,
      recommendation:
        "State whether data are aggregate, synthetic, de-identified, or sensitive.",
    },
    {
      title: "Ethics statement",
      passed: ["ethics", "irb", "institutional review", "consent"].some(
        (term) => text.includes(term),
      ),
      points: 6,
      recommendation:
        "State the ethics/IRB basis or explain why review was not required.",
    },
  ];

  const possible = results.reduce((sum, result) => sum + result.points, 0);
  const earned = results
    .filter((result) => result.passed)
    .reduce((sum, result) => sum + result.points, 0);
  const score = Math.round((earned / possible) * 100);
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
        (result) => `- **${result.title}:** ${result.recommendation}`,
      )
      .join("\n") || "- All configured quality checks passed.";

  return {
    repository,
    score,
    grade,
    markdown: `## Public Health Repository Quality: ${score}/100 (${grade})

| Check | Result | Points |
|---|---:|---:|
${rows}

### Recommended next steps

${recommendations}

_This automated review supports maintainers; it does not certify scientific validity, privacy compliance, or research ethics._`,
  };
}
