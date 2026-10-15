'use strict';

var CASES_DATA = [
  {
    id: 1,
    title: '山居茶室',
    category: 'space',
    desc: '为隐于山林的独立茶空间打造导视与环境图形，以克制的线条呼应自然肌理。'
  },
  {
    id: 2,
    title: '素元服饰',
    category: 'brand',
    desc: '从标志到包装的完整品牌识别系统，用留白与纸感传递手工织物的温度。'
  },
  {
    id: 3,
    title: '拾光书店',
    category: 'brand',
    desc: '社区独立书店的视觉重塑，以深墨色与暖纸色调构建安静的阅读氛围。'
  }
];

function renderCases(category) {
  var grid = document.getElementById('cases-grid');
  if (!grid) return;

  while (grid.firstChild) {
    grid.removeChild(grid.firstChild);
  }

  var filtered = category === 'all'
    ? CASES_DATA
    : CASES_DATA.filter(function(item) { return item.category === category; });

  filtered.forEach(function(item) {
    var div = document.createElement('div');
    div.className = 'case-item';

    var catSpan = document.createElement('span');
    catSpan.className = 'case-category';
    catSpan.textContent = item.category === 'brand' ? '品牌' : '空间';

    var titleEl = document.createElement('h3');
    titleEl.className = 'case-title';
    titleEl.textContent = item.title;

    var descEl = document.createElement('p');
    descEl.className = 'case-desc';
    descEl.textContent = item.desc;

    div.appendChild(catSpan);
    div.appendChild(titleEl);
    div.appendChild(descEl);
    grid.appendChild(div);
  });
}

function filterCases(category) {
  var buttons = document.querySelectorAll('.filter-btn');
  buttons.forEach(function(btn) {
    var isActive = btn.getAttribute('data-category') === category;
    if (isActive) {
      btn.classList.add('active');
      btn.setAttribute('aria-pressed', 'true');
    } else {
      btn.classList.remove('active');
      btn.setAttribute('aria-pressed', 'false');
    }
  });
  renderCases(category);
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function handleContactSubmit(event) {
  event.preventDefault();

  var nameInput = document.getElementById('name');
  var emailInput = document.getElementById('email');
  var descInput = document.getElementById('description');
  var errorEl = document.getElementById('error-message');
  var formEl = document.getElementById('contact-form');
  var successEl = document.getElementById('success-message');

  var nameVal = nameInput ? nameInput.value.trim() : '';
  var emailVal = emailInput ? emailInput.value.trim() : '';
  var descVal = descInput ? descInput.value.trim() : '';

  if (!nameVal || !emailVal || !descVal) {
    if (errorEl) {
      errorEl.textContent = '请填写所有必填项。';
      errorEl.removeAttribute('hidden');
    }
    return;
  }

  if (!validateEmail(emailVal)) {
    if (errorEl) {
      errorEl.textContent = '请输入有效的邮箱地址。';
      errorEl.removeAttribute('hidden');
    }
    return;
  }

  if (errorEl) {
    errorEl.textContent = '';
    errorEl.setAttribute('hidden', '');
  }

  if (formEl) formEl.setAttribute('hidden', '');
  if (successEl) successEl.removeAttribute('hidden');
}

function init() {
  var filterButtons = document.querySelectorAll('.filter-btn');
  filterButtons.forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      var category = e.currentTarget.getAttribute('data-category');
      if (category) {
        filterCases(category);
      }
    });
  });

  var contactForm = document.getElementById('contact-form');
  if (contactForm) {
    contactForm.addEventListener('submit', handleContactSubmit);
  }

  renderCases('all');
}

document.addEventListener('DOMContentLoaded', init);
