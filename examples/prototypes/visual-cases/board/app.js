'use strict';

const LANES = ['todo', 'inprogress', 'done'];
const LANE_LABELS = { todo: '待办', inprogress: '进行中', done: '已完成' };
const PRIORITY_LABELS = { low: '低', medium: '中', high: '高' };

let tasks = [
  { id: 'init-1', title: '设计数据库表结构', priority: 'high', lane: 'todo' },
  { id: 'init-2', title: '编写 API 接口文档', priority: 'medium', lane: 'inprogress' },
  { id: 'init-3', title: '搭建项目脚手架', priority: 'low', lane: 'done' }
];

let currentSearchQuery = '';

function initApp() {
  var btnAdd = document.getElementById('btn-add-task');
  var btnCancel = document.getElementById('btn-cancel');
  var form = document.getElementById('create-form');
  var searchInput = document.getElementById('search-input');
  var board = document.getElementById('board');

  btnAdd.addEventListener('click', openCreateDialog);
  btnCancel.addEventListener('click', closeCreateDialog);
  form.addEventListener('submit', handleFormSubmit);
  searchInput.addEventListener('input', handleSearchInput);
  board.addEventListener('click', handleBoardClick);

  renderBoard();
  updateStatistics();
}

function createTask(title, priority) {
  var trimmed = (title || '').trim();
  if (!trimmed) {
    throw new Error('Title is required');
  }
  var validPriorities = ['low', 'medium', 'high'];
  var safePriority = validPriorities.indexOf(priority) !== -1 ? priority : 'medium';
  var newTask = {
    id: Date.now().toString(),
    title: trimmed,
    priority: safePriority,
    lane: 'todo'
  };
  tasks.push(newTask);
  renderBoard();
  updateStatistics();
  closeCreateDialog();
}

function moveTaskToNextLane(taskId) {
  var task = null;
  for (var i = 0; i < tasks.length; i++) {
    if (tasks[i].id === taskId) {
      task = tasks[i];
      break;
    }
  }
  if (!task) return;
  var currentIndex = LANES.indexOf(task.lane);
  if (currentIndex < LANES.length - 1) {
    task.lane = LANES[currentIndex + 1];
  }
  renderBoard();
  updateStatistics();
}

function filterTasksByTitle(query) {
  currentSearchQuery = (query || '').toLowerCase().trim();
  renderBoard();
}

function getFilteredTasks() {
  if (!currentSearchQuery) return tasks;
  var result = [];
  for (var i = 0; i < tasks.length; i++) {
    if (tasks[i].title.toLowerCase().indexOf(currentSearchQuery) !== -1) {
      result.push(tasks[i]);
    }
  }
  return result;
}

function renderBoard() {
  var filtered = getFilteredTasks();
  for (var l = 0; l < LANES.length; l++) {
    var laneName = LANES[l];
    var laneEl = document.querySelector('.lane[data-lane="' + laneName + '"]');
    if (!laneEl) continue;
    var cardsContainer = laneEl.querySelector('.lane-cards');
    if (!cardsContainer) continue;

    while (cardsContainer.firstChild) {
      cardsContainer.removeChild(cardsContainer.firstChild);
    }

    for (var t = 0; t < filtered.length; t++) {
      var task = filtered[t];
      if (task.lane !== laneName) continue;
      cardsContainer.appendChild(createTaskCard(task));
    }
  }
}

function createTaskCard(task) {
  var card = document.createElement('div');
  card.className = 'task-card';
  card.setAttribute('data-task-id', task.id);

  var titleEl = document.createElement('p');
  titleEl.className = 'task-title';
  titleEl.textContent = task.title;
  card.appendChild(titleEl);

  var metaEl = document.createElement('div');
  metaEl.className = 'task-meta';

  var badge = document.createElement('span');
  badge.className = 'priority-badge priority-' + task.priority;
  badge.textContent = PRIORITY_LABELS[task.priority] || task.priority;
  metaEl.appendChild(badge);

  if (task.lane !== 'done') {
    var moveBtn = document.createElement('button');
    moveBtn.type = 'button';
    moveBtn.className = 'btn-move';
    moveBtn.setAttribute('data-action', 'move');
    moveBtn.setAttribute('data-task-id', task.id);
    moveBtn.setAttribute('aria-label', '将任务「' + task.title + '」移至下一列');
    var nextLaneIndex = LANES.indexOf(task.lane) + 1;
    moveBtn.textContent = '移至' + (LANE_LABELS[LANES[nextLaneIndex]] || '下一列');
    metaEl.appendChild(moveBtn);
  }

  card.appendChild(metaEl);
  return card;
}

function updateStatistics() {
  var counts = { todo: 0, inprogress: 0, done: 0 };
  for (var i = 0; i < tasks.length; i++) {
    if (counts.hasOwnProperty(tasks[i].lane)) {
      counts[tasks[i].lane]++;
    }
  }
  var statTodo = document.getElementById('stat-todo');
  var statInprogress = document.getElementById('stat-inprogress');
  var statDone = document.getElementById('stat-done');
  if (statTodo) statTodo.textContent = String(counts.todo);
  if (statInprogress) statInprogress.textContent = String(counts.inprogress);
  if (statDone) statDone.textContent = String(counts.done);
}

function openCreateDialog() {
  var dialog = document.getElementById('dialog-create');
  if (dialog && typeof dialog.showModal === 'function') {
    dialog.showModal();
  }
}

function closeCreateDialog() {
  var dialog = document.getElementById('dialog-create');
  var form = document.getElementById('create-form');
  var errorEl = document.getElementById('title-error');
  if (dialog && typeof dialog.close === 'function') {
    dialog.close();
  }
  if (form) form.reset();
  if (errorEl) errorEl.hidden = true;
}

function handleFormSubmit(event) {
  event.preventDefault();
  var titleInput = document.getElementById('input-title');
  var priorityInput = document.getElementById('input-priority');
  var errorEl = document.getElementById('title-error');
  var titleValue = titleInput ? titleInput.value : '';
  var priorityValue = priorityInput ? priorityInput.value : 'medium';

  try {
    createTask(titleValue, priorityValue);
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = err.message === 'Title is required' ? '标题为必填项' : err.message;
      errorEl.hidden = false;
    }
    if (titleInput) titleInput.focus();
  }
}

function handleSearchInput(event) {
  filterTasksByTitle(event.target.value);
}

function handleBoardClick(event) {
  var target = event.target;
  while (target && target !== event.currentTarget) {
    if (target.getAttribute && target.getAttribute('data-action') === 'move') {
      var taskId = target.getAttribute('data-task-id');
      if (taskId) {
        moveTaskToNextLane(taskId);
      }
      return;
    }
    target = target.parentNode;
  }
}

document.addEventListener('DOMContentLoaded', initApp);
