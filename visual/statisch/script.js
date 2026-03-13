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
    { text: '<Material><span class="xml-value">Powdercoating</span></Material>', cls: 'xml-tag xml-indent-2' },
    { text: '<Dimensions><span class="xml-value">600.0 x 117.0 x 12.0</span></Dimensions>', cls: 'xml-tag xml-indent-2' },
    { text: '<Finish><span class="xml-value">None</span></Finish>', cls: 'xml-tag xml-indent-2' },
    { text: '<Holes>', cls: 'xml-tag xml-indent-2' },
    { text: '<Hole type="<span class="xml-attr">tapped</span>"><span class="xml-value">2x M4</span></Hole>', cls: 'xml-tag xml-indent-3' },
    { text: '<Hole type="<span class="xml-attr">tapped</span>"><span class="xml-value">6x M6</span></Hole>', cls: 'xml-tag xml-indent-3' },
    { text: '<Hole type="<span class="xml-attr">through</span>"><span class="xml-value">2x normal</span></Hole>', cls: 'xml-tag xml-indent-3' },
    { text: '</Holes>', cls: 'xml-tag xml-indent-2' },
    { text: '<SurfaceFinish><span class="xml-value">ISO 4288</span></SurfaceFinish>', cls: 'xml-tag xml-indent-2' },
    { text: '<Tolerances><span class="xml-value">ISO 2768</span></Tolerances>', cls: 'xml-tag xml-indent-2' },
    { text: '<Warnings>', cls: 'xml-tag xml-indent-2' },
    { text: '<Warning><span class="xml-warning">⚠ LET OP: 6x tapgat M6</span></Warning>', cls: 'xml-tag xml-indent-3' },
    { text: '<Warning><span class="xml-warning">⚠ LET OP: 2x tapgat M4</span></Warning>', cls: 'xml-tag xml-indent-3' },
    { text: '</Warnings>', cls: 'xml-tag xml-indent-2' },
    { text: '</Item>', cls: 'xml-tag xml-indent-1' },
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
