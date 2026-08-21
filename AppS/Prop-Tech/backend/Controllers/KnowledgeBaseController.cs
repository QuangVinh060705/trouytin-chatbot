using Microsoft.AspNetCore.Mvc;
using backend.DTOs;
using backend.Services;
using Microsoft.AspNetCore.Authorization;
using System.Security.Claims;

namespace backend.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class KnowledgeBaseController : ControllerBase
{
    private readonly IKnowledgeBaseService _service;
    private readonly IChatbotIngestService _chatbotIngestService;

    public KnowledgeBaseController(
        IKnowledgeBaseService service,
        IChatbotIngestService chatbotIngestService)
    {
        _service = service;
        _chatbotIngestService = chatbotIngestService;
    }

    /// <summary>
    /// Lấy tất cả kiến thức (Admin/QuanLy xem tất cả, User thường chỉ xem active)
    /// </summary>
    [HttpGet]
    public async Task<ActionResult<List<KnowledgeBaseDto>>> GetAll([FromQuery] bool activeOnly = true)
    {
        try
        {
            var role = User.FindFirst(ClaimTypes.Role)?.Value;
            // Admin/QuanLy có thể xem cả inactive entries
            var canViewAll = role == "Admin" || role == "QuanLy";
            
            var items = await _service.GetAllAsync(User.GetOwnerUserId(), activeOnly || !canViewAll);
            return Ok(items);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Tìm kiếm kiến thức theo từ khóa
    /// </summary>
    [HttpGet("search")]
    public async Task<ActionResult<List<KnowledgeBaseDto>>> Search([FromQuery] string keyword)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(keyword))
            {
                return BadRequest(new { message = "Vui lòng nhập từ khóa tìm kiếm" });
            }

            var items = await _service.SearchAsync(keyword, User.GetOwnerUserId());
            return Ok(items);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Lấy kiến thức theo danh mục
    /// </summary>
    [HttpGet("category/{category}")]
    public async Task<ActionResult<List<KnowledgeBaseDto>>> GetByCategory(string category)
    {
        try
        {
            var items = await _service.GetByCategoryAsync(category, User.GetOwnerUserId());
            return Ok(items);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Lấy chi tiết kiến thức
    /// </summary>
    [HttpGet("{id}")]
    public async Task<ActionResult<KnowledgeBaseDto>> GetById(int id)
    {
        try
        {
            var item = await _service.GetByIdAsync(id, User.GetOwnerUserId());
            if (item == null)
            {
                return NotFound(new { message = "Không tìm thấy kiến thức này" });
            }
            return Ok(item);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Tạo kiến thức mới (Admin/QuanLy only)
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,QuanLy")]
    public async Task<ActionResult<KnowledgeBaseDto>> Create([FromBody] CreateKnowledgeBaseDto dto)
    {
        try
        {
            var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(new { message = "Không xác định được người dùng" });
            }

            var item = await _service.CreateAsync(dto, userId, User.GetOwnerUserId());
            return CreatedAtAction(nameof(GetById), new { id = item.Id }, item);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Cập nhật kiến thức (Admin/QuanLy only)
    /// </summary>
    [HttpPut("{id}")]
    [Authorize(Roles = "Admin,QuanLy")]
    public async Task<ActionResult<KnowledgeBaseDto>> Update(int id, [FromBody] UpdateKnowledgeBaseDto dto)
    {
        try
        {
            var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(new { message = "Không xác định được người dùng" });
            }

            var item = await _service.UpdateAsync(id, dto, userId, User.GetOwnerUserId());
            return Ok(item);
        }
        catch (InvalidOperationException ex)
        {
            return NotFound(new { message = ex.Message });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Xóa kiến thức (Admin only)
    /// </summary>
    [HttpDelete("{id}")]
    [Authorize(Roles = "Admin")]
    public async Task<IActionResult> Delete(int id)
    {
        try
        {
            await _service.DeleteAsync(id, User.GetOwnerUserId());
            return Ok(new { message = "Xóa kiến thức thành công" });
        }
        catch (InvalidOperationException ex)
        {
            return NotFound(new { message = ex.Message });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }

    /// <summary>
    /// Upload file PDF/DOCX/TXT để trích xuất kiến thức (Admin/QuảnLý only)
    /// </summary>
    [HttpPost("upload-document")]
    [Authorize(Roles = "Admin,QuanLy")]
    [Consumes("multipart/form-data")]
    public async Task<ActionResult<DocumentUploadResultDto>> UploadDocument(
        IFormFile file,
        [FromForm] string category = "Khác",
        [FromForm] bool autoActivate = true)
    {
        try
        {
            var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !int.TryParse(userIdClaim, out int userId))
                return Unauthorized(new { message = "Không xác định được người dùng" });

            if (file == null || file.Length == 0)
                return BadRequest(new { message = "Không có file được tải lên" });

            // Bỏ ".doc": chatApp chỉ hỗ trợ .pdf/.docx/.txt/.md (SUPPORTED_EXT
            // trong core/config.py), nên file .doc vẫn trích được kiến thức
            // nhưng ingest vào ChromaDB luôn thất bại -> admin thấy "trích được
            // N mục" kèm IngestSucceeded=false mà không rõ lý do.
            var allowedExtensions = new[] { ".pdf", ".docx", ".txt", ".md" };
            var extension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (!allowedExtensions.Contains(extension))
                return BadRequest(new { message = "Chỉ chấp nhận file PDF, DOCX, DOC, TXT" });

            if (file.Length > 10 * 1024 * 1024)
                return BadRequest(new { message = "Kích thước file không được vượt quá 10MB" });

            var result = await _service.UploadDocumentAsync(file, category, autoActivate, userId, User.GetOwnerUserId());
            if (result.TotalExtracted > 0)
            {
                var ingestResult = await _chatbotIngestService.RebuildAsync();
                result.IngestTriggered = ingestResult.Triggered;
                result.IngestSucceeded = ingestResult.Success;
                result.IngestMessage = ingestResult.Message;
                result.IngestDocuments = ingestResult.Documents;
            }

            return Ok(result);
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { message = ex.Message });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { message = "Đã xảy ra lỗi", error = ex.Message });
        }
    }
}
