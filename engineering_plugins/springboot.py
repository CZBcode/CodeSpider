import os

MANIFEST = {
    'api_version': '1.0', 'id': 'plugin.springboot', 'kind': 'plugin', 'name': 'Spring Boot 工程', 'version': '1.0.0', 'priority': 30,
    'description': 'Java Spring Boot 的 MVC 分层、Maven/Gradle 检测和工程测试。', 'project_types': ['java-springboot'],
    'keywords': ['java', 'spring', 'springboot', 'spring boot', 'maven', 'gradle', '后台接口'],
    'preferred_keywords': ['java', 'spring', 'springboot', 'spring boot'],
    'intent_keywords': ['管理系统', '教务', '学生', '课程', '成绩', '选课', '订单', '库存', '后台', '后端', '业务系统', '企业', 'backend', 'rest api'],
    'recommendation': '适合管理系统、业务接口和数据库服务，采用 MVC 分层。', 'recommendation_priority': 30,
    'verify_command': 'mvn -q test',
    'instructions': 'Separate controller, service, domain and repository responsibilities. Use only APIs/imports supported by the supplied build file. Avoid duplicate beans in test slices. In Spring Boot 3.x the Mockito test annotation is org.springframework.boot.test.mock.mockito.MockBean. Include service and HTTP contract tests.',
}

def detect(root):
    return bool(set(os.listdir(root)) & {'pom.xml', 'build.gradle', 'build.gradle.kts'})

def verification(root):
    files = set(os.listdir(root))
    command = 'mvn -q test' if 'pom.xml' in files else ('./gradlew test' if 'gradlew' in files else 'gradle test')
    return {'commands': [command, 'mvn spring-boot:run' if 'pom.xml' in files else 'gradle bootRun'], 'verify_command': command, 'verification_commands': [], 'setup_commands': []}
