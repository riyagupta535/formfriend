export type DecisionAnswer = {
  label: string;
  next_node_id: string | null;
  terminal_option: string | null;
};

export type DecisionNode = {
  node_id: string;
  question: string;
  helper_text: string | null;
  answers: DecisionAnswer[];
};

export type DecisionTree = {
  start_node_id: string;
  nodes: DecisionNode[];
};

export type DecisionStep = {
  node_id: string;
  answer_label: string;
};

function nodeById(tree: DecisionTree, nodeId: string): DecisionNode | undefined {
  return tree.nodes.find(node => node.node_id === nodeId);
}

export function currentDecisionNode(
  tree: DecisionTree,
  path: DecisionStep[],
): DecisionNode | null {
  let node = nodeById(tree, tree.start_node_id);
  if (!node) return null;

  for (const step of path) {
    if (step.node_id !== node.node_id) return null;
    const answer = node.answers.find(item => item.label === step.answer_label);
    if (!answer?.next_node_id) return null;
    node = nodeById(tree, answer.next_node_id);
    if (!node) return null;
  }
  return node;
}

export function chooseDecisionAnswer(
  tree: DecisionTree,
  path: DecisionStep[],
  answerLabel: string,
): { path: DecisionStep[]; terminalOption: string | null } {
  const node = currentDecisionNode(tree, path);
  if (!node) throw new Error("This decision path is no longer valid.");
  const answer = node.answers.find(item => item.label === answerLabel);
  if (!answer) throw new Error("Choose one of the available answers.");

  return {
    path: [...path, { node_id: node.node_id, answer_label: answer.label }],
    terminalOption: answer.terminal_option,
  };
}

