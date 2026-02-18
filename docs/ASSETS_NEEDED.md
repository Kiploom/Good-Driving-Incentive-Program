# Landing Page Assets Checklist

To make the landing dashboard look real and animated, add these images, videos, and GIFs to `flask/app/static/img/landing/`. Create the folder if it doesn't exist.

---

## Required Assets

### 1. Hero Image
| File | Description | Recommended size |
|------|-------------|------------------|
| **hero.jpg** | Full-width hero background. Trucks on highway, driver at wheel, or abstract rewards/points imagery. Should work with dark overlay. | 1920×1080 or 2560×1440 |

**How to add:** Place `hero.jpg` in `flask/app/static/img/landing/`. Then in `home.html`, update the hero section:
```html
<div class="landing-hero__bg" style="background-image: url('{{ url_for('static', filename='img/landing/hero.jpg') }}');" ...>
```

---

### 2. Points & Rewards Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **hero-points.jpg** or **hero-points.png** | Screenshot of driver points balance or points history page. Shows the points system in action. | 800×500 or similar 16:10 |

---

### 3. Product Catalog Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **catalog-demo.jpg** or **catalog-demo.gif** | Product grid / browse experience. GIF can show scrolling or hover effects. | 800×500 or 16:10 |

---

### 4. Mobile App Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **mobile-app.mp4** or **mobile-app.gif** | Phone mockup showing app screens. Screen recording of catalog, cart, or profile. | 16:9 or 9:16 (portrait phone) |

**Template change:** Replace the placeholder div content with:
```html
<video autoplay muted loop playsinline>
  <source src="{{ url_for('static', filename='img/landing/mobile-app.mp4') }}" type="video/mp4">
</video>
```

---

### 5. Orders Flow Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **orders-flow.gif** | Animated walkthrough: add to cart → checkout → order confirmation. Screen recording. | 900×506 (16:9) |

---

### 6. Sponsor Dashboard Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **sponsor-dashboard.jpg** | Sponsor's driver management or analytics view. Clean, professional screenshot. | 800×500 |

---

### 7. Leaderboard / Challenges Section
| File | Description | Recommended size |
|------|-------------|------------------|
| **leaderboard.jpg** or **challenges.jpg** | Leaderboard or challenge completion UI. Shows gamification. | 800×500 |

---

## Folder Structure

```
flask/app/static/img/landing/
├── hero.jpg
├── hero-points.jpg
├── catalog-demo.gif
├── mobile-app.mp4
├── orders-flow.gif
├── sponsor-dashboard.jpg
└── leaderboard.jpg
```

---

## Template Updates

After adding files, update `flask/app/templates/home.html`:

1. **Hero:** Uncomment or add the `background-image` style on `.landing-hero__bg` (see section 1 above).
2. **Media sections:** Replace each placeholder `<span>📸 filename</span>` with:
   - For images: `<img src="{{ url_for('static', filename='img/landing/filename.jpg') }}" alt="Description">`
   - For video: `<video autoplay muted loop playsinline><source src="..." type="video/mp4"></video>`
   - For GIF: `<img src="{{ url_for('static', filename='img/landing/filename.gif') }}" alt="Description">`

---

## Tips

- **GIFs** work well for short loops (5–15 seconds) showing interactions.
- **Videos** should be short, muted, and looped for best UX.
- Use **consistent aspect ratios** (16:10 or 16:9) for a polished look.
- **Compress** images (e.g. TinyPNG) to keep load times fast.
