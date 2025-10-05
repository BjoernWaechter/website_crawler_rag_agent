module "serverless-streamlit-app" {
  source          = "aws-ia/serverless-streamlit-app/aws"
  app_name        = "streamlit-app"
  app_version     = "v1.0.0"
  path_to_app_dir = "../streamlit" # Replace with path to your app
}