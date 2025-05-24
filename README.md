python3 -m venv venv

source venv/bin/activate

kubectl create -f job.yml

docker tag hellowhale-job:v1 vamsijakkula/hellowhale-job:v1
