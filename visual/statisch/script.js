/**
 * PDF Extractor Showcase — Interactive Animations
 * AI Doel
 */

document.addEventListener('DOMContentLoaded', () => {
  initScrollAnimations();
  initXMLDemo();
  initCounterAnimations();
});

/* =====================
   Scroll-triggered Fade-in
   ===================== */
function initScrollAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  });

  document.querySelectorAll('.fade-in').forEach(el => {
    observer.observe(el);
  });
}

/* =====================
   XML Demo — Typewriter Effect
   Shows AI Doel customer detection + full extraction
   ===================== */
function initXMLDemo() {
  const xmlLines = [
    { text: '&lt;?xml version="1.0" encoding="UTF-8"?&gt;', cls: 'xml-tag' },
    { text: '&lt;Order&gt;', cls: 'xml-tag' },
    { text: '&lt;Metadata&gt;', cls: 'xml-tag xml-indent-1' },
    { text: '&lt;DetectedCustomer&gt;<span class="xml-customer">AI DOEL</span>&lt;/DetectedCustomer&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Confidence&gt;<span class="xml-value">high</span>&lt;/Confidence&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;/Metadata&gt;', cls: 'xml-tag xml-indent-1' },
    { text: '&lt;Item&gt;', cls: 'xml-tag xml-indent-1' },
    { text: '&lt;PartNumber&gt;<span class="xml-value">AD-2026-00312</span>&lt;/PartNumber&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Name&gt;<span class="xml-value">Sheet</span>&lt;/Name&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Datum&gt;<span class="xml-value">13-03-2026</span>&lt;/Datum&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Material&gt;<span class="xml-value">S235</span>&lt;/Material&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Dimensions&gt;<span class="xml-value">600.0 x 117.0 x 12.0</span>&lt;/Dimensions&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Holes&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Hole type="<span class="xml-attr">tapped</span>"&gt;<span class="xml-value">4x M6</span>&lt;/Hole&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;Hole type="<span class="xml-attr">through</span>"&gt;<span class="xml-value">2x Ø12.5</span>&lt;/Hole&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;/Holes&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;TolerancedDiameters&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Diameter specification="<span class="xml-attr">H9</span>"&gt;<span class="xml-value">2x Ø20H9 (Reaming)</span>&lt;/Diameter&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;Diameter specification="<span class="xml-attr">custom</span>"&gt;<span class="xml-value">2x Ø40 +0.6/+0.1</span>&lt;/Diameter&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;/TolerancedDiameters&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;DeviatingSizes&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Size process="<span class="xml-attr">cutting</span>"&gt;<span class="xml-value">Ø19.5 (voor Ø20H9)</span>&lt;/Size&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;/DeviatingSizes&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Warnings&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;Warning&gt;<span class="xml-warning">⚠ LET OP: 4x tapgat M6</span>&lt;/Warning&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;Warning&gt;<span class="xml-warning">⚠ Afwijkende maattolerantie: Ø40 +0.6/+0.1</span>&lt;/Warning&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;Warning&gt;<span class="xml-warning">⚠ Twee reaming gaten: Ø19.5 → Ø20H9</span>&lt;/Warning&gt;', cls: 'xml-tag xml-indent-3' },
    { text: '&lt;/Warnings&gt;', cls: 'xml-tag xml-indent-2' },
    { text: '&lt;/Item&gt;', cls: 'xml-tag xml-indent-1' },
    { text: '&lt;/Order&gt;', cls: 'xml-tag' },
  ];

  const container = document.getElementById('xml-output');
  if (!container) return;

  // Pre-create all XML line elements
  xmlLines.forEach(line => {
    const div = document.createElement('div');
    div.className = `xml-line ${line.cls}`;
    div.innerHTML = line.text;
    container.appendChild(div);
  });

  // Animate when demo section scrolls into view
  let hasAnimated = false;
  const demoObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && !hasAnimated) {
        hasAnimated = true;
        animateXMLLines();
      }
    });
  }, { threshold: 0.3 });

  demoObserver.observe(container);
}

function animateXMLLines() {
  const lines = document.querySelectorAll('.xml-line');
  lines.forEach((line, index) => {
    setTimeout(() => {
      line.classList.add('visible');
    }, index * 100);
  });
}

/* =====================
   Counter Animations
   ===================== */
function initCounterAnimations() {
  const statValues = document.querySelectorAll('.stat-value[data-target]');

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animateCounter(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });

  statValues.forEach(el => observer.observe(el));
}

function animateCounter(element) {
  const target = parseFloat(element.dataset.target);
  const decimals = parseInt(element.dataset.decimals) || 0;
  const prefix = element.dataset.prefix || '';
  const suffix = element.dataset.suffix || '';
  const duration = 2000;
  const startTime = performance.now();

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);

    // Ease-out cubic
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = target * eased;

    element.textContent = `${prefix}${current.toFixed(decimals)}${suffix}`;

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      element.textContent = `${prefix}${target.toFixed(decimals)}${suffix}`;
    }
  }

  requestAnimationFrame(update);
}

/* =====================
   Smooth scroll for nav links
   ===================== */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});
