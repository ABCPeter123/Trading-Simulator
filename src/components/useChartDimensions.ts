import { useEffect, useRef, useState } from "react";

/**
 * Chart containers inside inactive workspace tabs have zero layout size.
 * Keep their charts unmounted until visible, then update dimensions whenever
 * a tab opens, a sidebar changes width, or a phone rotates.
 */
export function useChartDimensions() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => {
      const rect = element.getBoundingClientRect();
      // Integer device-independent pixels avoid re-render loops from
      // subpixel rounding during responsive layout calculations.
      const width = Math.max(0, Math.floor(rect.width));
      const height = Math.max(0, Math.floor(rect.height));
      setSize(previous =>
        previous.width === width && previous.height === height
          ? previous : { width, height },
      );
    };

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, []);

  return {
    ref,
    width: size.width,
    height: size.height,
    visible: size.width >= 12 && size.height >= 12,
  };
}
