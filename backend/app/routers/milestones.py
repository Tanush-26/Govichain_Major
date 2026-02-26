from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..models import (
    Milestone,
    Project,
    ProjectStatus,
    User,
    UserRole,
    MilestoneStatus
)
from ..schemas import MilestoneCreate, MilestoneResponse
from ..auth import get_current_user
from ..utils.rbac import require_role

router = APIRouter(prefix="/milestones", tags=["Milestones"])


# =========================================================
# CREATE MILESTONE
# =========================================================
@router.post("/", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED)
def create_milestone(
    milestone: MilestoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Only CONTRACTOR users can create milestones"""
    require_role([UserRole.CONTRACTOR])(current_user)

    project = db.query(Project).filter(Project.id == milestone.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    total_requested = db.query(Milestone).filter(
        Milestone.project_id == milestone.project_id
    ).with_entities(Milestone.requested_amount).all()

    total = sum(m[0] for m in total_requested) + milestone.requested_amount

    if total > project.budget:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total milestone amount (₹{total}) exceeds project budget (₹{project.budget})"
        )

    new_milestone = Milestone(
        project_id=milestone.project_id,
        title=milestone.title,
        description=milestone.description,
        requested_amount=milestone.requested_amount,
        contractor_id=current_user.id,
        status=MilestoneStatus.PENDING
    )

    db.add(new_milestone)
    db.commit()
    db.refresh(new_milestone)
    if project.status == ProjectStatus.CREATED:
        project.status = ProjectStatus.IN_PROGRESS
        db.commit()
        db.refresh(project)
    
    return new_milestone


# =========================================================
# GET MY MILESTONES (ROLE BASED)
# =========================================================
@router.get("/my-milestones", response_model=List[MilestoneResponse])
def get_my_milestones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get milestones based on user role"""
    if current_user.role == UserRole.CONTRACTOR:
        return db.query(Milestone).filter(
            Milestone.contractor_id == current_user.id
        ).all()

    elif current_user.role == UserRole.AUDITOR:
        return db.query(Milestone).filter(
            Milestone.status == MilestoneStatus.PENDING
        ).all()

    return db.query(Milestone).all()


# =========================================================
# FILTER MILESTONES BY STATUS
# =========================================================
@router.get("/filter/by-status", response_model=List[MilestoneResponse])
def filter_milestones_by_status(
    status: Optional[MilestoneStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Milestone)

    if status:
        query = query.filter(Milestone.status == status)

    return query.all()


# =========================================================
# GET PROJECT MILESTONES
# =========================================================
@router.get("/project/{project_id}", response_model=List[MilestoneResponse])
def get_project_milestones(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Milestone).filter(
        Milestone.project_id == project_id
    ).all()


# =========================================================
# GET MILESTONE BY ID
# =========================================================
@router.get("/{milestone_id}", response_model=MilestoneResponse)
def get_milestone(
    milestone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    milestone = db.query(Milestone).filter(
        Milestone.id == milestone_id
    ).first()

    if not milestone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone not found"
        )

    return milestone


# =========================================================
# APPROVE MILESTONE (AUDITOR)
# =========================================================
@router.put("/{milestone_id}/approve", response_model=MilestoneResponse)
def approve_milestone(
    milestone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Only AUDITOR users can approve milestones"""
    require_role([UserRole.AUDITOR])(current_user)
    
    milestone = db.query(Milestone).filter(Milestone.id == milestone_id).first()
    
    if not milestone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone not found"
        )
    
    if milestone.status != MilestoneStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Milestone is already {milestone.status.value}"
        )
    
    milestone.status = MilestoneStatus.APPROVED
    milestone.auditor_id = current_user.id
    milestone.approved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(milestone)
  
    project = db.query(Project).filter(Project.id == milestone.project_id).first()
    
    if project and project.status != ProjectStatus.COMPLETED:
        # Calculate total approved amount
        total_approved = db.query(func.sum(Milestone.requested_amount)).filter(
            Milestone.project_id == milestone.project_id,
            Milestone.status == MilestoneStatus.APPROVED
        ).scalar() or 0
        
        # If total approved amount equals or exceeds budget, mark as completed
        if total_approved >= project.budget:
            project.status = ProjectStatus.COMPLETED
            db.commit()
    
    return milestone


# =========================================================
# FLAG MILESTONE (AUDITOR)
# =========================================================
@router.put("/{milestone_id}/flag", response_model=MilestoneResponse)
def flag_milestone(
    milestone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_role([UserRole.AUDITOR])(current_user)

    milestone = db.query(Milestone).filter(
        Milestone.id == milestone_id
    ).first()

    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    if milestone.status != MilestoneStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Milestone is already {milestone.status.value}"
        )

    milestone.status = MilestoneStatus.FLAGGED
    milestone.auditor_id = current_user.id

    db.commit()
    db.refresh(milestone)

    return milestone
