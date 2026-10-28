from artiform.processors.base import SectionProcessor
from artiform.processors.cleanup_policies import CleanupPoliciesProcessor
from artiform.processors.members import MembersProcessor
from artiform.processors.repositories import RepositoriesProcessor

# Order matters: repositories must exist before cleanup policies reference
# them, and members are independent but kept between the two for readability.
SECTION_PROCESSORS: list[type[SectionProcessor]] = [
    RepositoriesProcessor,
    MembersProcessor,
    CleanupPoliciesProcessor,
]
