# Frontend Accessibility

For material UI, layout, or interaction changes, preserve the design system and platform interaction patterns. Keep portable behavior in the established components, controllers, view-models, hooks, or platform equivalents, and verify with platform-native accessibility APIs and supported assistive technology.

Cover applicable loading, empty, error, disabled, and success states; accessible names, keyboard or platform input, visible and sensible focus management, assistive-technology behavior, contrast, target size, and reduced-motion preference for new motion. Use available automated accessibility checks and rendered-state verification for material UI work.

For web surfaces, also verify semantic HTML, supported browsers and viewports, zoom/reflow, touch targets, and absence of unintended overflow, overlap, or clipping. For native/mobile/desktop surfaces, verify supported devices, form factors, orientations/window sizes, text scaling, platform focus/navigation, and relevant screen reader or accessibility-service behavior.

For an isolated copy, label, or tooltip-text change that does not alter layout or interaction, inspect the owning UI and run existing focused checks; use rendered verification when practical. Do not require the full platform, device, browser, viewport, zoom, reflow, touch-target, or manual accessibility matrix unless the change makes it relevant.
