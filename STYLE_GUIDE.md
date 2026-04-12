# Application Style Guide

This guide documents the visual design system, UI components, and coding conventions used in the Humanitarian Geocoder application. Use this reference to maintain consistency across future applications.

## 1. Color Palette

### Primary Colors
Used for main actions, buttons, and active states.
- **Primary Blue:** `#4A90E2` (Main actions, focus borders)
- **Primary Hover:** `#357ABD` (Hover state)
- **Primary Active:** `#2E6DA4` (Pressed state)
- **Focus Ring:** `rgba(74, 144, 226, 0.1)`

### Text Colors
- **Primary Text:** `#2c3e50` (Headings, Labels, Strong text)
- **Secondary Text:** `#7f8c8d` (Subtitles, Divider text, Footer)
- **Muted Text:** `#95a5a6` (Taglines, placeholders)
- **Body Text:** `#586069` (General content)

### UI & Backgrounds
- **Page Background:** `#f4f5f7` (Light gray/off-white)
- **Container Background:** `#ffffff` (White - Main cards)
- **Section Background:** `#f8f9fa` (Secondary areas like input groups)
- **Borders:** `#d1d5da` or `#e1e4e8`

### Status Colors
- **Success:**
  - Background: `#d4edda`
  - Border: `#c3e6cb`
  - Text: `#155724`
- **Error:**
  - Background: `#f8d7da` or `#fff5f5`
  - Border: `#f5c6cb` or `#feb2b2`
  - Text: `#721c24` or `#c53030`

---

## 2. Typography

**Font Stack:**
`'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`

### Scale
- **Tagline / Meta:** `10px - 11px` (Letter-spacing: `0.3px` to `0.5px`, often Italic)
- **Footer / Helper:** `12px`
- **Labels:** `13px` (Weight: 500)
- **Body / Inputs / Buttons:** `14px`
- **Section Headers (H2/H3):** `18px` (Weight: 500)
- **Page Title (H1):** `24px` (Weight: 500)

### Weights
- **Regular:** 400
- **Medium:** 500 (Used for buttons, inputs, headers)
- **Semi-Bold:** 600 (Used within result labels)

---

## 3. UI Components

### Containers & Cards
Standard content wrapper style.
```css
.container {
    background: white;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    padding: 32px 40px; /* or 48px 40px for login */
}
```

### Form Inputs
Standard text and password inputs.
```css
input[type="text"] {
    padding: 11px 12px;
    border: 1px solid #d1d5da;
    border-radius: 3px;
    font-size: 14px;
    font-family: inherit;
    transition: border-color 0.2s, box-shadow 0.2s;
}

/* Focus State */
input:focus {
    outline: none;
    border-color: #4A90E2; /* Primary Blue */
    box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
}
```

### Buttons
Primary action buttons.
```css
button, .btn-primary {
    padding: 12px 16px;
    background: #4A90E2;
    color: white;
    border: none;
    border-radius: 3px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s;
}

button:hover {
    background: #357ABD;
}
button:active {
    background: #2E6DA4;
}
```

### Secondary Buttons (e.g., Logout)
```css
.btn-secondary {
    background: white;
    color: #4A90E2;
    border: 1px solid #d1d5da;
}
```

---

## 4. Layout Principles

### Spacing System
The UI generally follows an 8-point grid system.
- **Micro:** 4px, 8px, 12px
- **Small:** 16px
- **Medium:** 24px
- **Large:** 32px, 40px, 48px

### CSS Reset
Minimal reset used:
```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}
```

---

## 5. Coding Conventions (Python/Flask)

Although visual consistency is key, matching code structure ensures maintainability.

- **Templates:** Store HTML in `templates/` folder.
- **Static Assets:** (Currently inline or CDN based) - Future apps should likely move styles to `static/css/style.css`.
- **Naming:**
  - CSS Classes: Kebab-case (e.g., `.logo-container`, `.login-prompt`).
  - IDs: Kebab-case (e.g., `#file-input`).
