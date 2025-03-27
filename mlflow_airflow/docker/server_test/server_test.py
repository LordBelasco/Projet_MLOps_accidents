from kubernetes.utils import create_from_yaml
from kubernetes import client, config, utils
from kubernetes.stream import stream
from kubernetes.client.rest import ApiException
import yaml
import os
import time
from dotenv import load_dotenv


class TestError(Exception):
    pass

def kubernetes_apply_yaml():

    # Charge automatiquement ~/.kube/config (monté depuis le host dans le container)
    config.load_kube_config()

    # lister les pods pour vérifier la connexion
    core_api = client.CoreV1Api()
    print("Listing pods in all namespaces:")
    pods = core_api.list_pod_for_all_namespaces()
    for pod in pods.items:
        print(f"{pod.metadata.namespace}/{pod.metadata.name}")

    # chemins
    yaml_path = "data/fastapi-test-job.yaml"
    namespace = "projet-mlops"
    job_name = "fastapi-tests"
    pv_name = "fastapi-tests"
    pvc_name = "fastapi-tests"

    batch_api = client.BatchV1Api()

    def ensure_namespace(namespace):
        # -------------- Namespace -----------------
        try:
            core_api.read_namespace(namespace)
            print(f"🔄 Namespace '{namespace}' mis à jour")
        except ApiException as e:
            print(e)
            if e.status == 404:
                namespace_body = client.V1Namespace(
                        metadata=client.V1ObjectMeta(name=namespace)
                    )
                core_api.create_namespace(body=namespace_body)
                print(f"✅ Namespace '{namespace}' créé")
            else:
                raise

    ensure_namespace(namespace)

    # yaml_path = "C:/Users/lordb/OneDrive/Documents/PTP/Projet MLOps/Projet_MLOps_accidents/mlflow_airflow/kube/docker/data_test/fastapi-test-job.yaml"

    with open(yaml_path, "r") as f:
        documents = list(yaml.safe_load_all(f))

    # met à jour le chemin du persistent volume à partir du .env
    load_dotenv()
    persistentvolume_hostPath_path = os.getenv("PERSISTENTVOLUME_HOSTPATH_PATH")
    documents[0]["spec"]["hostPath"]["path"] = persistentvolume_hostPath_path

    # Créer PV, PVC et Job
    create_from_yaml(client.ApiClient(), yaml_objects=documents, namespace=namespace)

    # Attendre que le Job démarre
    print("⏳ En attente de fin du Job...")

    try:
        while True:
            job_status = batch_api.read_namespaced_job_status(job_name, namespace)
            if job_status.status.succeeded is not None and job_status.status.succeeded >= 1:            
                break
            elif job_status.status.failed is not None and job_status.status.failed > 0:
                print("❌ Job a échoué.")
                raise TestError("Les tests ont échoué")
            time.sleep(2)
    finally:
        # Récupérer le nom du pod
        pods = core_api.list_namespaced_pod(namespace, label_selector=f"job-name={job_name}")
        pod_name = pods.items[0].metadata.name

        # Lire les logs
        print(f"\n📄 Logs du pod {pod_name} :\n")
        logs = core_api.read_namespaced_pod_log(name=pod_name, namespace=namespace)
        print(logs)

        # Lire l'état du pod
        pod_status = core_api.read_namespaced_pod_status(name=pod_name, namespace=namespace)
        # Récupérer l'état du conteneur
        container_status = pod_status.status.container_statuses[0]
        # Vérifier si le conteneur s'est terminé, récupére son exit code
        if container_status.state.terminated:
            exit_code = container_status.state.terminated.exit_code
        else:
            exit_code = 0

        # Supprimer les ressources de kub
        print("\n🧹 Nettoyage : suppression du Job, PVC et PV")
        batch_api.delete_namespaced_job(
            name=job_name,
            namespace=namespace,
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        )
        core_api.delete_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
        core_api.delete_persistent_volume(name=pv_name)

        # Remonte l'erreur au dag en utilisantr le exit_code
        if exit_code == 0:
            print("✅ Job terminé avec succès.")
        else:
            print("❌ Job a échoué.")
            raise TestError("Les tests ont échoué")

if __name__ == "__main__":
    kubernetes_apply_yaml()
