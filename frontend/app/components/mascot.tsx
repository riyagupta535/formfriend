export default function Mascot({
  small = false,
  talking = false,
}: {
  small?: boolean;
  talking?: boolean;
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
    </div>
  );
}
