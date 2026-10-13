// Spring depth fixture: @PreAuthorize auth, @Autowired DI,
// @ControllerAdvice error contract, @RequestBody DTO type.
// No Bean-Validation annotations — validation must be UNKNOWN.
package demo;

import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.beans.factory.annotation.Autowired;

@RestController
@RequestMapping("/api")
class PetController {
    @Autowired PetRepository repo;

    @PostMapping("/pets")
    @PreAuthorize("hasRole('ADMIN')")
    public Pet add(@RequestBody PetCreateDto body) {
        return null;
    }
}

@RestControllerAdvice
class GlobalAdvice {
    @ExceptionHandler(NotFound.class)
    public Pet on404() { return null; }
}
