function filterMembers(members, query) {
  const keyword = query.trim().toLowerCase();
  return members.filter(member => `${member.name} ${member.email}`.toLowerCase().includes(keyword));
}

function emptyMember() {
  return {name: '', email: '', role: '成员'};
}

new Vue({
  el: '#app',
  data() {
    return {
      query: '', dialogVisible: false, form: emptyMember(),
      members: [
        {id: 1, name: '林晓', email: 'lin@example.com', role: '管理员'},
        {id: 2, name: '周予', email: 'zhou@example.com', role: '成员'},
        {id: 3, name: '陈默', email: 'chen@example.com', role: '成员'}
      ],
      rules: {
        name: [{required: true, whitespace: true, message: '请输入姓名', trigger: 'blur'}],
        email: [{required: true, message: '请输入邮箱', trigger: 'blur'}, {type: 'email', message: '请输入有效邮箱', trigger: 'blur'}]
      }
    };
  },
  computed: {
    filteredMembers() { return filterMembers(this.members, this.query); },
    adminCount() { return this.members.filter(member => member.role === '管理员').length; }
  },
  methods: {
    openCreate() { this.form = emptyMember(); this.dialogVisible = true; },
    resetForm() { this.form = emptyMember(); this.$refs.memberForm.clearValidate(); },
    saveMember() {
      this.$refs.memberForm.validate(valid => {
        if (!valid) return;
        const email = this.form.email.trim().toLowerCase();
        if (this.members.some(member => member.email.toLowerCase() === email)) {
          this.$message.error('该邮箱已存在');
          return;
        }
        this.members.push({id: Date.now(), name: this.form.name.trim(), email, role: this.form.role});
        this.query = ''; this.dialogVisible = false;
        this.$message.success('成员已添加');
      });
    }
  }
});
