export default function Mascot({
  small = false,
  talking = false,
  mouthOpen = 0,
}: {
  small?: boolean;
  talking?: boolean;
  mouthOpen?: number;
}) {
  return (
    <div className={`mascot ${small ? "mascot-small" : ""} ${talking ? "talking" : ""}`}>
      <img
        src="/images/formfriend-mascot.png"
        alt="Your soft teal Form Friend, with paper antennae and a glowing golden light in its hands"
        width={1236}
        height={1272}
        draggable={false}
      />
      {mouthOpen > .025 && <svg className="mascot-mouth" viewBox="0 0 1236 1272" aria-hidden="true">
        <ellipse cx="695" cy="590" rx="49" ry="29" fill="#79d6d0" />
        <ellipse cx="695" cy="592" rx={31 - mouthOpen * 5} ry={4 + mouthOpen * 23} fill="#102c3d" stroke="#285365" strokeWidth="4" transform="rotate(-8 695 592)" />
        <ellipse cx="695" cy={596 + mouthOpen * 10} rx="13" ry={mouthOpen * 6} fill="#d98591" />
      </svg>}
    </div>
  );
}
