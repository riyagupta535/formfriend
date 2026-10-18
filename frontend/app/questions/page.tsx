import { redirect } from "next/navigation";
// Guided questions moved to the voice-and-text conversation at /guide.
export default function Questions(){redirect("/guide");}
