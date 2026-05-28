terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "agentops-terraform-state-prod"
    key    = "production/state.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}

# --- VPC NETWORK CORE ---
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "agentops-production-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b", "us-east-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = false
  
  tags = {
    Environment = "production"
    Team        = "AgentOps-Ops"
  }
}

# --- MANAGED DATABASE INSTANCE (POSTGRESQL) ---
resource "aws_db_instance" "postgres" {
  allocated_storage    = 50
  max_allocated_storage = 500
  db_name              = "agentops_prod_db"
  engine               = "postgres"
  engine_version       = "16.1"
  instance_class       = "db.r7g.large"
  username             = "agentops_db_admin"
  password             = var.db_password
  parameter_group_name = "default.postgres16"
  skip_final_snapshot  = false
  final_snapshot_identifier = "agentops-db-prod-final"
  
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]

  multi_az = true
}

# --- ELASTICACHE INSTANCE (REDIS COGNITIVE CACHE) ---
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id          = "agentops-redis-cluster"
  replication_group_description = "Cognitive Cache Episodic Cluster"
  node_type                     = "cache.m7g.large"
  num_cache_clusters            = 2
  parameter_group_name          = "default.redis7"
  port                          = 6379
  
  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  automatic_failover_enabled = true
}

# --- AWS ECS/EKS MODULE DECLARATION ---
# EKS / GKE cluster configurations would hook private subnet outputs from above
# to run the orchestrated Kubernetes pods.
