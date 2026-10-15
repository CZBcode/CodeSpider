/**
 * Filters members by case-insensitive name match.
 * @param {string} query - The search string to filter by.
 * @param {Array<{name:string,email:string,role:string,status:string}>} members - The full member list.
 * @returns {Array<{name:string,email:string,role:string,status:string}>} Filtered members.
 */
function filterMembers(query, members) {
  var trimmed = (query || '').trim().toLowerCase();
  if (!trimmed) {
    return members;
  }
  return members.filter(function (member) {
    return member.name.toLowerCase().indexOf(trimmed) !== -1;
  });
}

/**
 * Validates an email address format.
 * @param {string} email - The email string to validate.
 * @returns {boolean} True if the email format is valid.
 */
function validateEmail(email) {
  if (!email) return false;
  var re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(email);
}

new Vue({
  el: '#app',
  data: function () {
    return {
      searchQuery: '',
      dialogVisible: false,
      members: [
        { name: '林晓', email: 'linxiao@example.com', role: '管理员', status: '活跃' },
        { name: '周予', email: 'zhouyu@example.com', role: '编辑', status: '活跃' },
        { name: '陈默', email: 'chenmo@example.com', role: '查看者', status: '未激活' }
      ],
      newMember: {
        name: '',
        email: '',
        role: '查看者',
        status: '活跃'
      },
      rules: {
        name: [
          { required: true, message: '请输入姓名', trigger: 'blur' }
        ],
        email: [
          { required: true, message: '请输入邮箱', trigger: 'blur' },
          {
            validator: function (rule, value, callback) {
              if (!validateEmail(value)) {
                callback(new Error('邮箱格式不正确'));
              } else {
                callback();
              }
            },
            trigger: 'blur'
          }
        ]
      }
    };
  },
  computed: {
    filteredMembers: function () {
      return filterMembers(this.searchQuery, this.members);
    }
  },
  mounted: function () {
    this.$nextTick(function () {
      var tableBody = this.$el.querySelector('.el-table__body-wrapper');
      if (tableBody) {
        tableBody.setAttribute('tabindex', '0');
        tableBody.setAttribute('role', 'region');
        tableBody.setAttribute('aria-label', '成员列表数据区域');
      }
    }.bind(this));
  },
  methods: {
    _handleDialogKeydown: function (event) {
      if (event.key !== 'Tab') return;
      var dialogEl = document.querySelector('.member-dialog');
      if (!dialogEl) return;
      var focusableSelectors = 'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';
      var focusableEls = Array.prototype.slice.call(dialogEl.querySelectorAll(focusableSelectors)).filter(function (el) {
        return el.offsetParent !== null;
      });
      if (focusableEls.length === 0) return;
      var firstEl = focusableEls[0];
      var lastEl = focusableEls[focusableEls.length - 1];
      if (event.shiftKey) {
        if (document.activeElement === firstEl) {
          event.preventDefault();
          lastEl.focus();
        }
      } else {
        if (document.activeElement === lastEl) {
          event.preventDefault();
          firstEl.focus();
        }
      }
    },
    openAddDialog: function () {
      this.newMember = {
        name: '',
        email: '',
        role: '查看者',
        status: '活跃'
      };
      this.dialogVisible = true;
      this.$nextTick(function () {
        if (this.$refs.memberForm) {
          this.$refs.memberForm.clearValidate();
        }
        var dialogEl = document.querySelector('.member-dialog');
        if (dialogEl) {
          var nameInput = dialogEl.querySelector('input[type="text"]');
          if (nameInput) {
            nameInput.focus();
          }
          document.addEventListener('keydown', this._handleDialogKeydown);
        }
      }.bind(this));
    },
    closeAddDialog: function () {
      this.dialogVisible = false;
      document.removeEventListener('keydown', this._handleDialogKeydown);
      if (this.$refs.memberForm) {
        this.$refs.memberForm.resetFields();
      }
      this.$nextTick(function () {
        var addBtn = this.$el.querySelector('.toolbar .el-button--primary');
        if (addBtn) {
          addBtn.focus();
        }
      }.bind(this));
    },
    saveMember: function () {
      if (!this.$refs.memberForm) return;
      this.$refs.memberForm.validate(function (valid) {
        if (valid) {
          this.members.push({
            name: this.newMember.name,
            email: this.newMember.email,
            role: this.newMember.role,
            status: this.newMember.status
          });
          this.closeAddDialog();
        }
      }.bind(this));
    }
  }
});
