import { describe, expect, it } from "vitest";
import { chooseDecisionAnswer, currentDecisionNode, type DecisionTree } from "./decision-tree";

const tree: DecisionTree = {
  start_node_id: "married",
  nodes: [
    {
      node_id: "married",
      question: "Are you married?",
      helper_text: null,
      answers: [
        { label: "Yes", next_node_id: "joint", terminal_option: null },
        { label: "No", next_node_id: null, terminal_option: "Single" },
      ],
    },
    {
      node_id: "joint",
      question: "Will you file jointly?",
      helper_text: null,
      answers: [
        { label: "Yes", next_node_id: null, terminal_option: "Married filing jointly" },
        { label: "No", next_node_id: null, terminal_option: "Married filing separately" },
      ],
    },
  ],
};

describe("decision tree", () => {
  it("moves through conditional nodes and resolves an original option", () => {
    expect(currentDecisionNode(tree, [])?.node_id).toBe("married");
    const first = chooseDecisionAnswer(tree, [], "Yes");
    expect(first.terminalOption).toBeNull();
    expect(currentDecisionNode(tree, first.path)?.node_id).toBe("joint");

    const second = chooseDecisionAnswer(tree, first.path, "No");
    expect(second.terminalOption).toBe("Married filing separately");
  });

  it("can terminate without asking an irrelevant follow-up", () => {
    const result = chooseDecisionAnswer(tree, [], "No");
    expect(result.terminalOption).toBe("Single");
  });
});

