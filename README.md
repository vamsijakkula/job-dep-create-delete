To Run this Job 
****************
kubectl create -f hellowhale-sa.yml 
kubectl create -f hellowhale-role.yml
kubectl create -f hellowhale-rb.yml
kubectl create -f job.yml

Other Commands
*****************
python3 -m venv venv
source venv/bin/activate
docker tag hellowhale-job:v1 vamsijakkula/hellowhale-job:v1
