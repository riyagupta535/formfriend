export default function Mascot({
  small = false,
  talking = false,
  mouthOpen = 0,
  flipped = false,
}: {
  small?: boolean;
  talking?: boolean;
  mouthOpen?: number;
  flipped?: boolean;
}) {
  const openness = Math.min(1, Math.max(0, mouthOpen));
  const mouthHeight = 5 + openness * 22;
  return (
    <div className={`mascot ${small ? "mascot-small" : ""} ${talking ? "talking" : ""} ${flipped ? "mascot-flipped" : ""}`}>
      <img
        src="/images/formfriend-mascot-top-hat.png"
        alt="Fomy, your friendly teal guide wearing a navy top hat with a teal band"
        width={1236}
        height={1272}
        draggable={false}
      />
      {openness > .025 && <svg className="mascot-mouth" viewBox="0 0 1236 1272" aria-hidden="true">
        <ellipse cx="695" cy="590" rx="49" ry="29" fill="#79d6d0" />
        <g transform="rotate(-8 695 592)">
          <ellipse cx="695" cy="592" rx={36 - openness * 5} ry={mouthHeight} fill="#102c3d" stroke="#285365" strokeWidth="3" />
          <ellipse className="mascot-tongue" cx="695" cy={592 + mouthHeight * .45} rx={18 * openness} ry={9 * openness} fill="#ef9ca8" />
          <ellipse cx="691" cy={591 + mouthHeight * .45} rx={6 * openness} ry={2 * openness} fill="#ffc5cb" />
        </g>
      </svg>}
    </div>
  );
}
