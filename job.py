# job_script.py

import time
import os
import yaml # Import the yaml library
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes import utils # Import utils for applying YAML
from kubernetes.watch import Watch # Explicitly import Watch

# Load Kubernetes configuration
# This will automatically detect if running inside a cluster (in-cluster config)
# or outside (kubeconfig file).
try:
    config.load_incluster_config()
    print("Running in-cluster configuration.")
except config.config_exception.ConfigException:
    try:
        config.load_kube_config()
        print("Running with kubeconfig file.")
    except config.config_exception.ConfigException:
        print("Could not load Kubernetes configuration. Exiting.")
        exit(1)

# Initialize Kubernetes API clients
apps_v1 = client.AppsV1Api()
core_v1 = client.CoreV1Api()

# Define the namespace where the resources will be created/deleted
NAMESPACE = "default"
# Path to the combined YAML file inside the container
RESOURCES_YAML_PATH = "hellowhale.yml"
WAIT_SECONDS = 60

# Global list to store the names and kinds of resources successfully created by this job
# This helps in knowing what to delete later.
created_resources_info = [] # Format: [{'kind': 'Deployment', 'name': 'hello-blue-whale'}, {'kind': 'Service', 'name': 'hello-whale-svc'}]

def create_resources_from_yaml():
    """
    Reads the combined YAML file, creates all resources defined within it,
    and stores their information for later deletion using kubernetes.utils.
    """
    global created_resources_info
    created_resources_info = [] # Reset for each run

    print(f"Attempting to create resources from '{RESOURCES_YAML_PATH}' in namespace '{NAMESPACE}' using kubernetes.utils...")

    try:
        with open(RESOURCES_YAML_PATH, 'r') as f:
            # yaml.safe_load_all() loads all YAML documents from the stream
            manifests = list(yaml.safe_load_all(f)) # Load all manifests into a list first

            for manifest in manifests:
                if not manifest: # Skip empty documents if any
                    continue

                kind = manifest.get('kind')
                name = manifest.get('metadata', {}).get('name')

                if not kind or not name:
                    print(f"Skipping malformed or incomplete manifest: {manifest}")
                    continue

                print(f"Processing {kind}: {name}...")

                try:
                    # Use kubernetes.utils.create_from_dict for more robust resource creation
                    # It handles the API version and kind mapping automatically.
                    # It returns the created Kubernetes object.
                    # Note: create_from_dict can sometimes return a list if the manifest
                    # itself contains multiple documents or is interpreted as such.
                    created_obj_or_list = utils.create_from_dict(client.ApiClient(), manifest, namespace=NAMESPACE)

                    # Handle both single object and list of objects returned by create_from_dict
                    if isinstance(created_obj_or_list, list):
                        for created_item in created_obj_or_list:
                            if hasattr(created_item, 'kind') and hasattr(created_item, 'metadata') and hasattr(created_item.metadata, 'name'):
                                actual_kind = created_item.kind
                                actual_name = created_item.metadata.name
                                print(f"Successfully created {actual_kind} '{actual_name}'.")
                                created_resources_info.append({'kind': actual_kind, 'name': actual_name})
                            else:
                                print(f"Warning: Created item in list has unexpected structure. Cannot track for deletion: {created_item}")
                    else: # Assume it's a single object
                        created_obj = created_obj_or_list
                        if hasattr(created_obj, 'kind') and hasattr(created_obj, 'metadata') and hasattr(created_obj.metadata, 'name'):
                            actual_kind = created_obj.kind
                            actual_name = created_obj.metadata.name
                            print(f"Successfully created {actual_kind} '{actual_name}'.")
                            created_resources_info.append({'kind': actual_kind, 'name': actual_name})
                        else:
                            print(f"Warning: Created object for {kind} '{name}' has unexpected structure. Cannot track for deletion.")
                            # Fallback to original manifest's kind/name if object structure is unexpected
                            created_resources_info.append({'kind': kind, 'name': name})

                except ApiException as e:
                    if e.status == 409: # Conflict, resource already exists
                        print(f"Resource '{kind}' named '{name}' already exists. Skipping creation.")
                        # Even if it exists, we still want to track it for deletion in this run
                        created_resources_info.append({'kind': kind, 'name': name})
                    else:
                        print(f"Error creating {kind} '{name}': {e}")
                        raise # Re-raise the exception to terminate the job if creation fails unexpectedly
                except Exception as e:
                    print(f"An unexpected error occurred while processing {kind} '{name}': {e}")
                    raise # Re-raise for general errors during creation

    except FileNotFoundError:
        print(f"Error: YAML file not found at '{RESOURCES_YAML_PATH}'.")
        raise
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file '{RESOURCES_YAML_PATH}': {e}")
        raise

def wait_for_deployment_ready():
    """
    Identifies the deployment from the created_resources_info and waits for it to be ready.
    Assumes there's at least one Deployment resource managed by this job.
    """
    deployment_to_wait_for = None
    for res_info in created_resources_info:
        if res_info['kind'] == 'Deployment':
            deployment_to_wait_for = res_info['name']
            break

    if not deployment_to_wait_for:
        print("No Deployment resource found in the YAML to wait for readiness. Skipping wait.")
        return

    print(f"Waiting for deployment '{deployment_to_wait_for}' to be ready...")
    w = Watch() # Changed to use the directly imported Watch class
    try:
        # Use a reasonable timeout for the watch stream (e.g., 10 minutes)
        for event in w.stream(apps_v1.list_namespaced_deployment, namespace=NAMESPACE, field_selector=f"metadata.name={deployment_to_wait_for}", timeout_seconds=600):
            if event['type'] == 'ADDED' or event['type'] == 'MODIFIED':
                deployment = event['object']
                # Check if observedGeneration matches metadata.generation to ensure all updates are processed
                # and if ready_replicas matches expected replicas.
                if deployment.status and \
                   deployment.status.ready_replicas == deployment.spec.replicas and \
                   deployment.metadata.generation == deployment.status.observed_generation:
                    print(f"Deployment '{deployment_to_wait_for}' is ready.")
                    w.stop()
                    return
            # Provide more detailed status during the wait
            current_replicas = deployment.status.ready_replicas if deployment.status and deployment.status.ready_replicas is not None else 0
            desired_replicas = deployment.spec.replicas if deployment.spec and deployment.spec.replicas is not None else 'N/A'
            print(f"Deployment '{deployment_to_wait_for}' not yet ready. Current status: {event['type'] if 'type' in event else 'Unknown'}, Ready Replicas: {current_replicas}/{desired_replicas}")
        print(f"Timeout waiting for deployment '{deployment_to_wait_for}' to be ready.")
    except ApiException as e:
        print(f"Kubernetes API error while waiting for deployment: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while waiting for deployment readiness: {e}")
    finally:
        w.stop() # Ensure the watch is stopped even on error or timeout

def delete_created_resources():
    """
    Deletes all resources that were previously created and tracked by this job.
    Deletes in reverse order of creation, which can sometimes help with dependencies.
    """
    print("Attempting to delete created resources...")
    # Iterate in reverse to delete dependents first (e.g., Deployment before Service in some cases)
    # However, for simple Deployment/Service, order often doesn't strictly matter for deletion.
    for resource_info in reversed(created_resources_info):
        kind = resource_info['kind']
        name = resource_info['name']
        print(f"Deleting {kind} '{name}' from namespace '{NAMESPACE}'...")
        try:
            # Use kubernetes.utils.delete_from_dict for more robust resource deletion
            # This requires the full manifest, but we only have kind/name.
            # So, we'll stick to direct API calls for deletion, which is fine.
            if kind == 'Deployment':
                apps_v1.delete_namespaced_deployment(
                    name=name,
                    namespace=NAMESPACE,
                    body=client.V1DeleteOptions(propagation_policy="Foreground", grace_period_seconds=5)
                )
                print(f"Deployment '{name}' deletion initiated.")
            elif kind == 'Service':
                core_v1.delete_namespaced_service(
                    name=name,
                    namespace=NAMESPACE,
                    body=client.V1DeleteOptions(propagation_policy="Foreground", grace_period_seconds=5)
                )
                print(f"Service '{name}' deletion initiated.")
            else:
                print(f"Skipping deletion for unsupported resource kind '{kind}'.")
        except ApiException as e:
            if e.status == 404: # Not Found, resource already gone
                print(f"Resource '{kind}' named '{name}' not found. Skipping deletion.")
            else:
                print(f"Error deleting {kind} '{name}': {e}")
                # Don't re-raise, try to delete other resources even if one fails

def main():
    """
    Main function to orchestrate the job's tasks.
    """
    try:
        # 1. Create resources (Deployment and Service) from the combined YAML
        create_resources_from_yaml()

        # 2. Wait for the specific deployment to be ready
        wait_for_deployment_ready()

        # 3. Wait for 60 seconds
        print(f"Waiting for {WAIT_SECONDS} seconds...")
        time.sleep(WAIT_SECONDS)
        print("Wait complete.")

        # 4. Delete all the created resources (Deployment and Service)
        delete_created_resources()

        # 5. Terminate the job
        print("Job completed successfully. Terminating.")

    except Exception as e:
        print(f"An error occurred during job execution: {e}")
        # Exit with a non-zero status code to indicate failure
        os._exit(1)

if __name__ == "__main__":
    main()
