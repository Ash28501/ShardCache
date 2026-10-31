pipeline {
  agent any
  stages {
    stage('Install') {
      steps { sh 'python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest ruff' }
    }
    stage('Lint') {
      steps { sh '. .venv/bin/activate && ruff check .' }
    }
    stage('Test') {
      steps { sh '. .venv/bin/activate && pytest -q --junitxml=reports/tests.xml' }
      post { always { junit 'reports/tests.xml' } }
    }
    stage('Benchmark') {
      steps { sh '. .venv/bin/activate && python -m bench.bench_sharding | tee reports/bench.txt' }
    }
    stage('Build image') {
      steps { sh 'docker build -t shardcache:${BUILD_NUMBER} .' }
    }
    stage('Deploy') {
      when { branch 'main' }
      steps { sh 'docker compose up -d --build shardcache' }
    }
  }
  post { always { archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true } }
}
