import type { EvaluationMetrics } from "../api/types";

type MetricSummaryProps = {
  metrics: EvaluationMetrics;
};

const ratioMetrics: Array<{
  key: keyof EvaluationMetrics;
  label: string;
  definition: string;
}> = [
  {
    key: "top_five_hit_rate",
    label: "Top-five hit rate",
    definition: "Expected source appears in first five results.",
  },
  {
    key: "mean_reciprocal_rank",
    label: "Mean reciprocal rank",
    definition: "Average reciprocal rank of first relevant result.",
  },
  {
    key: "citation_structural_validity",
    label: "Citation structural validity",
    definition: "Citation passage, offsets, and hashes are structurally valid.",
  },
  {
    key: "citation_correctness",
    label: "Citation correctness",
    definition: "Structurally valid citations support their linked claims.",
  },
  {
    key: "gold_citation_coverage",
    label: "Gold citation coverage",
    definition: "Answers cite at least one benchmark gold source.",
  },
  {
    key: "answer_faithfulness",
    label: "Answer faithfulness",
    definition: "Atomic answer claims are supported by supplied evidence.",
  },
  {
    key: "abstention_accuracy",
    label: "Abstention accuracy",
    definition: "Answer versus abstain behavior matches benchmark expectation.",
  },
  {
    key: "facet_abstention_accuracy",
    label: "Facet abstention accuracy",
    definition: "Each multi-part question facet is answered or withheld correctly.",
  },
];

export function MetricSummary({ metrics }: MetricSummaryProps) {
  return (
    <section className="metric-summary" aria-label="Aggregate metrics">
      <dl>
        {ratioMetrics.map((metric) => (
          <div key={metric.key}>
            <dt>{metric.label}</dt>
            <dd>{Math.round(Number(metrics[metric.key]) * 100)}%</dd>
            <small>{metric.definition}</small>
          </div>
        ))}
        <div>
          <dt>Median latency</dt>
          <dd>{metrics.median_latency_ms} ms</dd>
          <small>Median end-to-end response latency.</small>
        </div>
        <div>
          <dt>P95 latency</dt>
          <dd>{metrics.p95_latency_ms} ms</dd>
          <small>95th-percentile end-to-end response latency.</small>
        </div>
        <div>
          <dt>Question failures</dt>
          <dd>{metrics.question_failures}</dd>
          <small>Questions that failed independently during execution.</small>
        </div>
      </dl>
    </section>
  );
}
