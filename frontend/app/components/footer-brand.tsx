"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import Logo from "./logo";

export default function FooterBrand() {
  const [scrollable, setScrollable] = useState(false);
  const brand = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const measure = () => {
      const footer = brand.current?.closest("footer");
      if (!footer) return;
      // Footer padding or a few pixels of overflow should not count as a long page.
      const footerTop = footer.getBoundingClientRect().top + window.scrollY;
      setScrollable(footerTop > document.documentElement.clientHeight + 1);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(document.body);
    observer?.observe(document.documentElement);
    window.addEventListener("resize", measure);
    measure();
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  // Preserve the space so showing the logo cannot itself change scrollability.
  return <Link ref={brand} href="/" className="footer-brand" aria-label="Forma home"
    style={{ visibility: scrollable ? "visible" : "hidden" }}
    aria-hidden={!scrollable} tabIndex={scrollable ? undefined : -1}>
    <Logo />
  </Link>;
}
